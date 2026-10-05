"""Read-only queries over the inventory ledger, for investigating count discrepancies.

These back the investigator's tools and the chat's. None of them reads ``shelf_variance``:
an investigation only sees what a real warehouse system would record.
"""

from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel
from sqlmodel import Session, col, select

from warehouse_ops.db.models import (
    CycleCount,
    Inventory,
    InventoryTxn,
    Location,
    LocationType,
    Order,
    OrderLine,
    PickTask,
    PickTaskStatus,
    Sku,
    TxnType,
)
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.inventory import get_sku
from warehouse_ops.services.schemas import LocalDateTime

MAX_HISTORY = 100


class LedgerEntry(BaseModel):
    ts: LocalDateTime
    location: str
    sku_code: str
    lpn: str | None
    qty_change: int
    type: TxnType
    user: str
    reason: str  # "" when nobody gave one
    ref: str | None
    balance_after: int  # system qty at this location for this SKU right after the change


class LastCount(BaseModel):
    counted_at: LocalDateTime
    system_qty: int
    counted_qty: int
    status: str


class NearbySlot(BaseModel):
    location: str
    type: LocationType
    bay: int
    level: int
    sku_code: str | None  # None = nothing recorded here
    description: str | None
    lpn: str | None
    qty: int
    last_count: LastCount | None


class OpenPick(BaseModel):
    pick_task_id: int
    order_number: str
    sku_code: str
    expected_qty: int
    order_created_at: LocalDateTime


def _location(session: Session, code: str) -> Location:
    location = session.exec(select(Location).where(Location.code == code.strip().upper())).first()
    if location is None:
        raise NotFoundError(f"No location with code {code!r}")
    return location


def get_inventory_history(
    session: Session,
    *,
    location: str | None = None,
    sku_code: str | None = None,
    user: str | None = None,
    txn_type: TxnType | None = None,
    since: datetime | None = None,
    limit: int = MAX_HISTORY,
) -> list[LedgerEntry]:
    """Ledger rows matching the filters, oldest first (the newest ``limit`` of them).

    At least one of location, SKU or user is required, so a call can't dump the whole ledger.
    """
    if not (location or sku_code or user):
        raise RuleViolationError("Give a location, a SKU code or a user to search the history")

    statement = select(InventoryTxn)
    if location:
        statement = statement.where(InventoryTxn.location_id == _location(session, location).id)
    if sku_code:
        statement = statement.where(InventoryTxn.sku_id == get_sku(session, sku_code).id)
    if user:
        statement = statement.where(col(InventoryTxn.user).ilike(f"%{user.strip()}%"))
    if txn_type:
        statement = statement.where(InventoryTxn.type == txn_type)
    if since:
        statement = statement.where(col(InventoryTxn.ts) >= since)
    newest_first = statement.order_by(col(InventoryTxn.ts).desc(), col(InventoryTxn.id).desc())
    rows = list(session.exec(newest_first.limit(limit)))
    rows.reverse()

    # Running balance per location and SKU, over each one's full history.
    balances: dict[int, int] = {}
    for key in {(r.location_id, r.sku_id) for r in rows}:
        running = 0
        for txn in session.exec(
            select(InventoryTxn)
            .where(InventoryTxn.location_id == key[0], InventoryTxn.sku_id == key[1])
            .order_by(col(InventoryTxn.ts), col(InventoryTxn.id))
        ):
            running += txn.qty_change
            assert txn.id is not None
            balances[txn.id] = running

    codes = _codes(session, {r.location_id for r in rows})
    skus = _sku_codes(session, {r.sku_id for r in rows})
    return [
        LedgerEntry(
            ts=r.ts,
            location=codes[r.location_id],
            sku_code=skus[r.sku_id],
            lpn=r.lpn,
            qty_change=r.qty_change,
            type=r.type,
            user=r.user,
            reason=r.reason,
            ref=r.ref,
            balance_after=balances[r.id or 0],
        )
        for r in rows
    ]


def get_nearby_stock(session: Session, location: str, bays: int = 2) -> list[NearbySlot]:
    """Slots in the same aisle within ``bays`` bays either side: their stock and last count."""
    here = _location(session, location)
    slots = session.exec(
        select(Location)
        .where(
            Location.zone == here.zone,
            Location.aisle == here.aisle,
            col(Location.bay).between(here.bay - bays, here.bay + bays),
            Location.type != LocationType.STAGING,
        )
        .order_by(col(Location.bay), col(Location.level))
    ).all()
    ids = [s.id for s in slots]
    stock: dict[int, list[Inventory]] = defaultdict(list)
    for row in session.exec(select(Inventory).where(col(Inventory.location_id).in_(ids))):
        stock[row.location_id].append(row)
    last_counts: dict[int, CycleCount] = {}
    for count in session.exec(
        select(CycleCount)
        .where(col(CycleCount.location_id).in_(ids))
        .order_by(col(CycleCount.counted_at), col(CycleCount.id))
    ):
        last_counts[count.location_id] = count  # later rows win
    skus = {s.id: s for s in session.exec(select(Sku))}

    result = []
    for slot in slots:
        assert slot.id is not None
        held: list[Inventory | None] = list(stock[slot.id]) or [None]
        last = last_counts.get(slot.id)
        for inv in held:
            sku = skus.get(inv.sku_id) if inv else None
            result.append(
                NearbySlot(
                    location=slot.code,
                    type=slot.type,
                    bay=slot.bay,
                    level=slot.level,
                    sku_code=sku.sku_code if sku else None,
                    description=sku.description if sku else None,
                    lpn=inv.lpn if inv else None,
                    qty=inv.qty if inv else 0,
                    last_count=LastCount(
                        counted_at=last.counted_at,
                        system_qty=last.system_qty,
                        counted_qty=last.counted_qty,
                        status=last.status,
                    )
                    if last
                    else None,
                )
            )
    return result


def list_open_picks(session: Session, location: str) -> list[OpenPick]:
    """Pick tasks at a location that haven't been confirmed yet (stock may already be in a tote)."""
    here = _location(session, location)
    rows = session.exec(
        select(PickTask, OrderLine, Order)
        .join(OrderLine, col(OrderLine.id) == col(PickTask.order_line_id))
        .join(Order, col(Order.id) == col(OrderLine.order_id))
        .where(PickTask.location_id == here.id, PickTask.status == PickTaskStatus.OPEN)
        .order_by(col(Order.created_at))
    ).all()
    skus = _sku_codes(session, {line.sku_id for _, line, _ in rows})
    return [
        OpenPick(
            pick_task_id=task.id or 0,
            order_number=order.order_number,
            sku_code=skus[line.sku_id],
            expected_qty=task.expected_qty,
            order_created_at=order.created_at,
        )
        for task, line, order in rows
    ]


def _codes(session: Session, ids: set[int]) -> dict[int, str]:
    return {
        loc.id: loc.code
        for loc in session.exec(select(Location).where(col(Location.id).in_(ids)))
        if loc.id is not None
    }


def _sku_codes(session: Session, ids: set[int]) -> dict[int, str]:
    return {
        sku.id: sku.sku_code
        for sku in session.exec(select(Sku).where(col(Sku.id).in_(ids)))
        if sku.id is not None
    }
