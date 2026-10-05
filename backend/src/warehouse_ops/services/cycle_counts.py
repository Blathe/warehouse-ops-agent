"""Cycle counts and the discrepancies they open (see docs/spec.md, "Cycle Count Investigator").

A count compares what a clerk found with what the system says. Matching counts are just
recorded; a mismatch opens a discrepancy that a supervisor resolves by accepting it (the
system is adjusted to the count, with a required reason) or asking for a recount.

The counts are simulated: the counted qty is the system qty plus the hidden
``shelf_variance`` for that location. Nothing outside this module and the evals reads
that table. Like the other write services, these functions don't commit.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from random import Random
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from warehouse_ops.db.models import (
    CountStatus,
    CycleCount,
    Inventory,
    InventoryTxn,
    Investigation,
    InvestigationStatus,
    Location,
    Picker,
    PickTask,
    PickTaskStatus,
    ShelfVariance,
    Sku,
    TxnType,
)
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.schemas import LocalDateTime

SAMPLE_SIZE = 30  # locations per simulated count, like one clerk's shift
OPEN_STATUSES = (CountStatus.DISCREPANCY, CountStatus.RECOUNT_REQUESTED)
FALLBACK_COUNTER = "Inventory clerk"

Key = tuple[int, int]  # (location_id, sku_id)


class Cause(BaseModel):
    cause: str = Field(description="What probably happened, in one sentence.")
    likelihood: Literal["high", "medium", "low"]
    evidence: list[str] = Field(
        description="Specific facts from the data: dates, quantities, users, refs, locations."
    )


class InvestigationOut(BaseModel):
    id: int
    status: InvestigationStatus
    model: str
    summary: str | None
    causes: list[Cause]
    next_steps: list[str]
    error: str | None
    tool_calls: int
    started_at: LocalDateTime
    finished_at: LocalDateTime | None


class CycleCountOut(BaseModel):
    id: int
    location: str
    sku_code: str
    description: str
    case_qty: int
    lpn: str | None
    counted_by: str
    counted_at: LocalDateTime
    system_qty: int
    counted_qty: int
    variance: int  # counted - system
    status: CountStatus
    resolved_by: str | None
    resolved_at: LocalDateTime | None
    resolution_reason: str | None
    investigation: InvestigationOut | None = None  # the latest one


class CycleCountRun(BaseModel):
    counted: int
    matched: int
    discrepancies: list[CycleCountOut]


def simulate_cycle_count(
    session: Session, *, rng: Random, now: datetime, sample_size: int = SAMPLE_SIZE
) -> CycleCountRun:
    """Count every location with a hidden variance plus a random sample of the rest.

    Locations with an open discrepancy are skipped; ones waiting for a recount are counted
    again. On a recount, counting artefacts (``transient`` variances) don't repeat, and an
    in-progress pick has been confirmed by then.
    """
    open_keys = {
        (c.location_id, c.sku_id)
        for c in session.exec(
            select(CycleCount).where(CycleCount.status == CountStatus.DISCREPANCY)
        )
    }
    recounts: dict[Key, list[CycleCount]] = {}
    for c in session.exec(
        select(CycleCount).where(CycleCount.status == CountStatus.RECOUNT_REQUESTED)
    ):
        recounts.setdefault((c.location_id, c.sku_id), []).append(c)
    hidden = {(v.location_id, v.sku_id): v for v in session.exec(select(ShelfVariance))}
    stock = {(i.location_id, i.sku_id): i for i in session.exec(select(Inventory))}

    # Targets keep their insertion order: planted problems, recounts, then the sample.
    targets: dict[Key, str | None] = {}  # key -> lpn
    for key, row in hidden.items():
        if key not in open_keys:
            targets[key] = row.lpn
    for key, counts in recounts.items():
        targets[key] = counts[0].lpn
    others = sorted(key for key in stock if key not in targets and key not in open_keys)
    for key in rng.sample(others, min(len(others), max(0, sample_size - len(targets)))):
        targets[key] = stock[key].lpn

    counter = rng.choice(_counters(session))
    results = []
    for key, lpn in targets.items():
        is_recount = key in recounts
        for old in recounts.get(key, []):
            old.status = CountStatus.RECOUNTED
            session.add(old)

        variance: ShelfVariance | None = hidden.get(key)
        if variance is not None and variance.transient and is_recount:
            if variance.scenario == "mid_pick_count":
                _confirm_open_pick(session, key, -variance.delta, now)
            session.delete(variance)
            variance = None

        inventory = session.exec(
            select(Inventory).where(Inventory.location_id == key[0], Inventory.sku_id == key[1])
        ).first()
        system_qty = inventory.qty if inventory else 0
        counted_qty = system_qty + (variance.delta if variance else 0)
        count = CycleCount(
            location_id=key[0],
            sku_id=key[1],
            lpn=lpn,
            counted_by=counter,
            counted_at=now,
            system_qty=system_qty,
            counted_qty=counted_qty,
            variance=counted_qty - system_qty,
            status=CountStatus.MATCHED if counted_qty == system_qty else CountStatus.DISCREPANCY,
        )
        session.add(count)
        results.append(count)

    session.flush()
    discrepancies = [c for c in results if c.status == CountStatus.DISCREPANCY]
    return CycleCountRun(
        counted=len(results),
        matched=len(results) - len(discrepancies),
        discrepancies=[_to_out(session, c) for c in discrepancies],
    )


def accept_cycle_count(
    session: Session, *, count_id: int, decided_by: str, reason: str, now: datetime
) -> CycleCountOut:
    """Adjust the system by the counted variance. A reason is required."""
    count = _open_count(session, count_id, decided_by)
    if not reason.strip():
        raise RuleViolationError("A reason is required to accept a count")

    inventory = session.exec(
        select(Inventory).where(
            Inventory.location_id == count.location_id, Inventory.sku_id == count.sku_id
        )
    ).first()
    current = inventory.qty if inventory else 0
    new_qty = current + count.variance
    if new_qty < 0:
        raise RuleViolationError(
            f"Only {current} left in the system, so a variance of {count.variance} can't apply"
        )

    if inventory is None:
        if count.lpn:
            elsewhere = session.exec(select(Inventory).where(Inventory.lpn == count.lpn)).first()
            if elsewhere is not None:
                at = session.get(Location, elsewhere.location_id)
                raise RuleViolationError(
                    f"{count.lpn} is still recorded at {at.code if at else 'another location'}; "
                    "resolve that count first"
                )
        session.add(
            Inventory(
                location_id=count.location_id,
                sku_id=count.sku_id,
                lpn=count.lpn,
                qty=new_qty,
                received_at=now,
            )
        )
    elif new_qty == 0:
        session.delete(inventory)
    else:
        inventory.qty = new_qty
        session.add(inventory)

    session.add(
        InventoryTxn(
            ts=now,
            location_id=count.location_id,
            sku_id=count.sku_id,
            lpn=count.lpn,
            qty_change=count.variance,
            type=TxnType.COUNT_ADJUSTMENT,
            user=decided_by.strip(),
            reason=reason.strip(),
            ref=f"cycle_count:{count.id}",
        )
    )

    # The shelf hasn't changed, only the system: what's left of the hidden variance is the
    # physical difference minus what was just adjusted (zero when the count was right).
    variance = session.exec(
        select(ShelfVariance).where(
            ShelfVariance.location_id == count.location_id, ShelfVariance.sku_id == count.sku_id
        )
    ).first()
    if variance is not None:
        physical = 0 if variance.transient else variance.delta
        variance.delta = physical - count.variance
        variance.transient = False
        if variance.delta == 0:
            session.delete(variance)
        else:
            session.add(variance)

    _resolve(count, CountStatus.ACCEPTED, decided_by, now, reason.strip())
    session.add(count)
    session.flush()
    return _to_out(session, count)


def request_recount(
    session: Session, *, count_id: int, decided_by: str, now: datetime
) -> CycleCountOut:
    """Send the location back to be counted again on the next count."""
    count = _open_count(session, count_id, decided_by)
    _resolve(count, CountStatus.RECOUNT_REQUESTED, decided_by, now, None)
    session.add(count)
    session.flush()
    return _to_out(session, count)


def get_cycle_count(session: Session, count_id: int) -> CycleCountOut:
    count = session.get(CycleCount, count_id)
    if count is None:
        raise NotFoundError(f"No cycle count #{count_id}")
    return _to_out(session, count)


def list_cycle_counts(
    session: Session, statuses: Sequence[CountStatus] | None = None, limit: int = 200
) -> list[CycleCountOut]:
    """Counts newest first, optionally only some statuses."""
    statement = select(CycleCount).order_by(
        col(CycleCount.counted_at).desc(), col(CycleCount.id).desc()
    )
    if statuses is not None:
        statement = statement.where(col(CycleCount.status).in_(statuses))
    return [_to_out(session, c) for c in session.exec(statement.limit(limit))]


def _open_count(session: Session, count_id: int, decided_by: str) -> CycleCount:
    count = session.get(CycleCount, count_id)
    if count is None:
        raise NotFoundError(f"No cycle count #{count_id}")
    if count.status != CountStatus.DISCREPANCY:
        raise RuleViolationError(f"Count #{count_id} is {count.status}, not an open discrepancy")
    if not decided_by.strip():
        raise RuleViolationError("decided_by is required")
    return count


def _resolve(
    count: CycleCount, status: CountStatus, by: str, now: datetime, reason: str | None
) -> None:
    count.status = status
    count.resolved_by = by.strip()
    count.resolved_at = now
    count.resolution_reason = reason


def _counters(session: Session) -> list[str]:
    """Clerks who receive stock also count it."""
    names = sorted(
        set(
            session.exec(
                select(InventoryTxn.user).where(InventoryTxn.type == TxnType.RECEIVE)
            ).all()
        )
    )
    return names or [FALLBACK_COUNTER]


def _confirm_open_pick(session: Session, key: Key, qty: int, now: datetime) -> None:
    """The picker confirms the pick that was in progress during the first count."""
    task = session.exec(
        select(PickTask).where(
            PickTask.location_id == key[0],
            PickTask.status == PickTaskStatus.OPEN,
            PickTask.expected_qty == qty,
        )
    ).first()
    inventory = session.exec(
        select(Inventory).where(Inventory.location_id == key[0], Inventory.sku_id == key[1])
    ).first()
    if task is None or inventory is None or inventory.qty < qty:
        return
    picker = session.exec(select(Picker).order_by(col(Picker.id))).first()
    task.status = PickTaskStatus.PICKED
    task.picked_qty = qty
    task.completed_at = now
    task.picker_id = picker.id if picker else None
    inventory.qty -= qty
    session.add_all([task, inventory])
    session.add(
        InventoryTxn(
            ts=now,
            location_id=key[0],
            sku_id=key[1],
            qty_change=-qty,
            type=TxnType.PICK,
            user=picker.name if picker else "unknown",
            ref=f"pick_task:{task.id}",
        )
    )


def _to_out(session: Session, count: CycleCount) -> CycleCountOut:
    location = session.get(Location, count.location_id)
    sku = session.get(Sku, count.sku_id)
    assert count.id is not None and location is not None and sku is not None
    return CycleCountOut(
        id=count.id,
        location=location.code,
        sku_code=sku.sku_code,
        description=sku.description,
        case_qty=sku.case_qty,
        lpn=count.lpn,
        counted_by=count.counted_by,
        counted_at=count.counted_at,
        system_qty=count.system_qty,
        counted_qty=count.counted_qty,
        variance=count.variance,
        status=count.status,
        resolved_by=count.resolved_by,
        resolved_at=count.resolved_at,
        resolution_reason=count.resolution_reason,
        investigation=latest_investigation(session, count.id),
    )


def latest_investigation(session: Session, count_id: int) -> InvestigationOut | None:
    row = session.exec(
        select(Investigation)
        .where(Investigation.cycle_count_id == count_id)
        .order_by(col(Investigation.id).desc())
    ).first()
    return investigation_out(row) if row else None


def investigation_out(row: Investigation) -> InvestigationOut:
    assert row.id is not None
    return InvestigationOut(
        id=row.id,
        status=row.status,
        model=row.model,
        summary=row.summary,
        causes=[Cause.model_validate(c) for c in json.loads(row.causes_json)],
        next_steps=json.loads(row.next_steps_json),
        error=row.error,
        tool_calls=row.tool_calls,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )
