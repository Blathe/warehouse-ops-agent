"""Creating and deciding replenishment tasks (the only writes in the system).

Every rule from docs/spec.md is checked here, not in a prompt, so it holds no matter
who calls: the MCP tool, the agent or the API. These functions add or change rows but
don't commit; the caller owns the transaction (like a unit of work in EF Core).
"""

from collections.abc import Sequence
from datetime import datetime

from sqlmodel import Session, col, func, select

from warehouse_ops.db.models import (
    Inventory,
    Location,
    LocationType,
    PickFace,
    ReplenishmentStatus,
    ReplenishmentTask,
    Sku,
)
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.inventory import get_sku
from warehouse_ops.services.replenishment import OPEN_REPLENISHMENT_STATUSES
from warehouse_ops.services.schemas import ReplenishmentTaskOut

MAX_RESULTS = 200


def get_location(session: Session, code: str) -> Location:
    location = session.exec(select(Location).where(Location.code == code.strip().upper())).first()
    if location is None:
        raise NotFoundError(f"No location with code {code!r}")
    return location


def create_replenishment_task(
    session: Session,
    *,
    sku_code: str,
    from_location: str,
    to_location: str,
    qty: int,
    reason: str,
    created_by: str,
    now: datetime,
) -> ReplenishmentTaskOut:
    """Propose moving ``qty`` of a SKU from a reserve pallet to its pick face.

    The task is created as PROPOSED; only ``decide_replenishment_task`` approves it.
    Raises NotFoundError for unknown codes and RuleViolationError for broken rules.
    """
    sku = get_sku(session, sku_code)
    source = get_location(session, from_location)
    target = get_location(session, to_location)
    assert sku.id is not None and source.id is not None and target.id is not None

    face = session.exec(select(PickFace).where(PickFace.sku_id == sku.id)).one()
    if face.location_id != target.id:
        home = session.get(Location, face.location_id)
        assert home is not None
        raise RuleViolationError(
            f"{target.code} is not the pick face for SKU {sku.sku_code}; "
            f"its pick face is {home.code}"
        )

    if source.type != LocationType.RESERVE:
        raise RuleViolationError(f"{source.code} is a {source.type} location, not a reserve slot")
    pallet = session.exec(
        select(Inventory).where(Inventory.location_id == source.id, Inventory.sku_id == sku.id)
    ).first()
    if pallet is None:
        raise RuleViolationError(f"{source.code} holds no stock of SKU {sku.sku_code}")

    if qty <= 0:
        raise RuleViolationError("qty must be greater than 0")
    if qty > pallet.qty:
        raise RuleViolationError(f"{source.code} only holds {pallet.qty}, so {qty} can't be moved")

    on_hand = session.exec(
        select(func.coalesce(func.sum(Inventory.qty), 0)).where(Inventory.location_id == target.id)
    ).one()
    if on_hand + qty > face.max_qty:
        raise RuleViolationError(
            f"{target.code} has {on_hand} on hand and a max of {face.max_qty}, "
            f"so at most {face.max_qty - on_hand} can be added (asked for {qty})"
        )

    existing = session.exec(
        select(ReplenishmentTask).where(
            ReplenishmentTask.to_location_id == target.id,
            col(ReplenishmentTask.status).in_(OPEN_REPLENISHMENT_STATUSES),
        )
    ).first()
    if existing is not None:
        raise RuleViolationError(
            f"Task #{existing.id} ({existing.status}) is already open for {target.code}"
        )

    if not reason.strip():
        raise RuleViolationError("A reason is required")

    task = ReplenishmentTask(
        sku_id=sku.id,
        from_location_id=source.id,
        to_location_id=target.id,
        lpn=pallet.lpn,
        qty=qty,
        reason=reason.strip(),
        status=ReplenishmentStatus.PROPOSED,
        created_by=created_by,
        created_at=now,
    )
    session.add(task)
    session.flush()  # assigns task.id
    return _to_out(session, task)


def decide_replenishment_task(
    session: Session, *, task_id: int, approve: bool, decided_by: str, now: datetime
) -> ReplenishmentTaskOut:
    """Approve or reject a PROPOSED task. Meant for a human: not exposed as an MCP tool."""
    task = session.get(ReplenishmentTask, task_id)
    if task is None:
        raise NotFoundError(f"No replenishment task #{task_id}")
    if task.status != ReplenishmentStatus.PROPOSED:
        raise RuleViolationError(
            f"Task #{task_id} is {task.status}, only PROPOSED tasks can be decided"
        )
    if not decided_by.strip():
        raise RuleViolationError("decided_by is required")

    task.status = ReplenishmentStatus.APPROVED if approve else ReplenishmentStatus.REJECTED
    task.approved_by = decided_by.strip()
    task.decided_at = now
    session.add(task)
    session.flush()
    return _to_out(session, task)


def get_replenishment_task(session: Session, task_id: int) -> ReplenishmentTaskOut:
    task = session.get(ReplenishmentTask, task_id)
    if task is None:
        raise NotFoundError(f"No replenishment task #{task_id}")
    return _to_out(session, task)


def list_replenishment_tasks(
    session: Session,
    statuses: Sequence[ReplenishmentStatus] | None = None,
    limit: int = MAX_RESULTS,
) -> list[ReplenishmentTaskOut]:
    """Replenishment tasks, newest first. Every status unless ``statuses`` narrows it."""
    statement = (
        select(ReplenishmentTask)
        .order_by(col(ReplenishmentTask.created_at).desc(), col(ReplenishmentTask.id).desc())
        .limit(limit)
    )
    if statuses is not None:
        statement = statement.where(col(ReplenishmentTask.status).in_(statuses))
    return [_to_out(session, task) for task in session.exec(statement)]


def _to_out(session: Session, task: ReplenishmentTask) -> ReplenishmentTaskOut:
    sku = session.get(Sku, task.sku_id)
    source = session.get(Location, task.from_location_id)
    target = session.get(Location, task.to_location_id)
    assert task.id is not None and sku and source and target
    return ReplenishmentTaskOut(
        task_id=task.id,
        status=task.status,
        sku_code=sku.sku_code,
        description=sku.description,
        from_location=source.code,
        to_location=target.code,
        lpn=task.lpn,
        qty=task.qty,
        reason=task.reason,
        created_by=task.created_by,
        created_at=task.created_at,
        approved_by=task.approved_by,
        decided_at=task.decided_at,
    )
