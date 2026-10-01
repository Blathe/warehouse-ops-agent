from collections import defaultdict

from sqlmodel import Session, col, func, select

from warehouse_ops.db.models import (
    Inventory,
    Location,
    LocationType,
    PickFace,
    PickTask,
    PickTaskStatus,
    ReplenishmentStatus,
    ReplenishmentTask,
    Sku,
)
from warehouse_ops.services.schemas import Pallet, ReplenishmentNeed

OPEN_REPLENISHMENT_STATUSES = (ReplenishmentStatus.PROPOSED, ReplenishmentStatus.APPROVED)


def list_replenishment_needs(
    session: Session, *, zone: str | None = None, include_open_demand: bool = True
) -> list[ReplenishmentNeed]:
    """Pick faces that need refilling, most urgent first.

    A face needs replenishment when on-hand is at or below min or, if
    ``include_open_demand``, below the qty on its open pick tasks.
    """
    face_query = (
        select(PickFace, Location, Sku)
        .join(Location, col(Location.id) == col(PickFace.location_id))
        .join(Sku, col(Sku.id) == col(PickFace.sku_id))
    )
    if zone:
        face_query = face_query.where(Location.zone == zone.upper())
    faces = session.exec(face_query).all()

    on_hand: dict[int, int] = defaultdict(int)
    for location_id, qty in session.exec(
        select(Inventory.location_id, func.sum(Inventory.qty))
        .join(Location, col(Location.id) == col(Inventory.location_id))
        .where(Location.type == LocationType.PICK)
        .group_by(col(Inventory.location_id))
    ):
        on_hand[location_id] = qty

    open_demand: dict[int, int] = defaultdict(int)
    for location_id, qty in session.exec(
        select(PickTask.location_id, func.sum(PickTask.expected_qty))
        .where(PickTask.status == PickTaskStatus.OPEN)
        .group_by(col(PickTask.location_id))
    ):
        open_demand[location_id] = qty

    # Oldest reserve pallet per SKU (FIFO source).
    oldest_pallet: dict[int, Pallet] = {}
    for inv, location in session.exec(
        select(Inventory, Location)
        .join(Location, col(Location.id) == col(Inventory.location_id))
        .where(Location.type == LocationType.RESERVE)
        .order_by(col(Inventory.received_at), col(Location.code))
    ):
        oldest_pallet.setdefault(
            inv.sku_id,
            Pallet(
                location=location.code, lpn=inv.lpn or "", qty=inv.qty, received_at=inv.received_at
            ),
        )

    open_tasks = {
        task.to_location_id: task.id
        for task in session.exec(
            select(ReplenishmentTask).where(
                col(ReplenishmentTask.status).in_(OPEN_REPLENISHMENT_STATUSES)
            )
        )
    }

    needs = []
    for face, location, sku in faces:
        qty = on_hand[face.location_id]
        demand = open_demand[face.location_id]
        reasons = []
        if qty <= face.min_qty:
            reasons.append("at or below min" if qty else "empty")
        if include_open_demand and qty < demand:
            reasons.append("below open pick demand")
        if not reasons:
            continue

        source = oldest_pallet.get(face.sku_id)
        whole_cases = (face.max_qty - qty) // sku.case_qty * sku.case_qty
        needs.append(
            ReplenishmentNeed(
                location=location.code,
                zone=location.zone,
                sku_code=sku.sku_code,
                description=sku.description,
                on_hand=qty,
                min_qty=face.min_qty,
                max_qty=face.max_qty,
                open_demand=demand,
                reasons=reasons,
                suggested_qty=min(whole_cases, source.qty) if source else 0,
                source=source,
                open_task_id=open_tasks.get(face.location_id),
            )
        )

    # Empty faces first, then by how far below min / demand they are.
    needs.sort(key=lambda n: (n.on_hand > 0, n.on_hand - max(n.min_qty, n.open_demand), n.location))
    return needs
