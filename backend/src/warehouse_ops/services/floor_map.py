"""The data behind the floor map: every bay with its pick face status and reserve pallets.

A bay is one x/y spot on the floor: a pick face at level 1 with reserve slots above it.
Pick face status uses the same rule as replenishment: at or below min is "low".
"""

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session, col, select

from warehouse_ops.db.models import (
    CycleCount,
    Inventory,
    Location,
    LocationType,
    PickFace,
    ReplenishmentTask,
    Sku,
)
from warehouse_ops.services.cycle_counts import OPEN_STATUSES as OPEN_COUNT_STATUSES
from warehouse_ops.services.replenishment import OPEN_REPLENISHMENT_STATUSES

PickStatus = Literal["ok", "low", "empty", "unassigned"]


class PickSlot(BaseModel):
    location: str
    sku_code: str | None  # None when no SKU is slotted here
    description: str | None
    on_hand: int
    min_qty: int | None
    max_qty: int | None
    status: PickStatus
    open_task_id: int | None  # PROPOSED/APPROVED replenishment task for this face


class ReserveSlot(BaseModel):
    location: str
    level: int
    sku_code: str | None  # None = empty slot
    lpn: str | None
    qty: int


class Bay(BaseModel):
    zone: str
    aisle: int
    bay: int
    x: int
    y: int
    pick: PickSlot
    reserve: list[ReserveSlot]  # lowest level first
    open_discrepancies: list[str] = []  # location codes in this bay with an open count


class StagingLane(BaseModel):
    location: str
    x: int
    y: int


class FloorMap(BaseModel):
    bays: list[Bay]  # ordered by zone, aisle, bay
    staging: list[StagingLane]
    counts: dict[PickStatus, int]


def get_floor_map(session: Session) -> FloorMap:
    locations = session.exec(
        select(Location).order_by(
            col(Location.zone), col(Location.aisle), col(Location.bay), col(Location.level)
        )
    ).all()
    skus = {s.id: s for s in session.exec(select(Sku))}
    faces = {f.location_id: f for f in session.exec(select(PickFace))}

    stock: dict[int, list[Inventory]] = defaultdict(list)
    for inv in session.exec(select(Inventory)):
        stock[inv.location_id].append(inv)

    open_tasks = {
        task.to_location_id: task.id
        for task in session.exec(
            select(ReplenishmentTask).where(
                col(ReplenishmentTask.status).in_(OPEN_REPLENISHMENT_STATUSES)
            )
        )
    }

    open_counts = {
        count.location_id
        for count in session.exec(
            select(CycleCount).where(col(CycleCount.status).in_(OPEN_COUNT_STATUSES))
        )
    }

    bays: dict[tuple[str, int, int], Bay] = {}
    staging = []
    counts: dict[PickStatus, int] = {"ok": 0, "low": 0, "empty": 0, "unassigned": 0}
    for loc in locations:
        assert loc.id is not None
        key = (loc.zone, loc.aisle, loc.bay)
        if loc.type == LocationType.STAGING:
            staging.append(StagingLane(location=loc.code, x=loc.x, y=loc.y))
            continue
        if loc.type == LocationType.PICK:
            pick = _pick_slot(loc, faces.get(loc.id), stock[loc.id], skus, open_tasks)
            counts[pick.status] += 1
            bays[key] = Bay(
                zone=loc.zone, aisle=loc.aisle, bay=loc.bay, x=loc.x, y=loc.y, pick=pick, reserve=[]
            )
        else:
            pallet = stock[loc.id][0] if stock[loc.id] else None
            sku = skus.get(pallet.sku_id) if pallet else None
            # Locations are ordered by level, so the bay's pick face (level 1) exists already.
            bays[key].reserve.append(
                ReserveSlot(
                    location=loc.code,
                    level=loc.level,
                    sku_code=sku.sku_code if sku else None,
                    lpn=pallet.lpn if pallet else None,
                    qty=pallet.qty if pallet else 0,
                )
            )
        if loc.id in open_counts:
            bays[key].open_discrepancies.append(loc.code)

    return FloorMap(bays=list(bays.values()), staging=staging, counts=counts)


def _pick_slot(
    loc: Location,
    face: PickFace | None,
    stock: list[Inventory],
    skus: dict[int | None, Sku],
    open_tasks: dict[int, int | None],
) -> PickSlot:
    assert loc.id is not None
    on_hand = sum(i.qty for i in stock)
    if face is None:
        return PickSlot(
            location=loc.code,
            sku_code=None,
            description=None,
            on_hand=on_hand,
            min_qty=None,
            max_qty=None,
            status="unassigned",
            open_task_id=None,
        )
    sku = skus[face.sku_id]
    status: PickStatus = "empty" if on_hand == 0 else "low" if on_hand <= face.min_qty else "ok"
    return PickSlot(
        location=loc.code,
        sku_code=sku.sku_code,
        description=sku.description,
        on_hand=on_hand,
        min_qty=face.min_qty,
        max_qty=face.max_qty,
        status=status,
        open_task_id=open_tasks.get(loc.id),
    )
