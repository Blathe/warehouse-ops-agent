from sqlmodel import Session, col, select

from warehouse_ops.db.models import (
    Inventory,
    Location,
    LocationType,
    PickFace,
    ReplenishmentTask,
    Sku,
)
from warehouse_ops.services.errors import NotFoundError
from warehouse_ops.services.replenishment import OPEN_REPLENISHMENT_STATUSES
from warehouse_ops.services.schemas import Pallet, PickFaceStock, SkuInfo, StockReport


def get_sku(session: Session, sku_code: str) -> Sku:
    sku = session.exec(select(Sku).where(Sku.sku_code == sku_code.strip())).first()
    if sku is None:
        raise NotFoundError(f"No SKU with code {sku_code!r}")
    return sku


def reserve_pallets(session: Session, sku_id: int) -> list[Pallet]:
    """Every reserve pallet of a SKU, oldest first (the order to use them in)."""
    rows = session.exec(
        select(Inventory, Location)
        .join(Location, col(Location.id) == col(Inventory.location_id))
        .where(Inventory.sku_id == sku_id, Location.type == LocationType.RESERVE)
        .order_by(col(Inventory.received_at), col(Location.code))
    )
    return [
        Pallet(location=location.code, lpn=inv.lpn or "", qty=inv.qty, received_at=inv.received_at)
        for inv, location in rows
    ]


def find_stock(session: Session, sku_code: str) -> StockReport:
    """Where a SKU is: its pick face (with min/max) and every reserve pallet."""
    sku = get_sku(session, sku_code)
    assert sku.id is not None

    face, location = session.exec(
        select(PickFace, Location)
        .join(Location, col(Location.id) == col(PickFace.location_id))
        .where(PickFace.sku_id == sku.id)
    ).one()
    on_hand = sum(
        session.exec(select(Inventory.qty).where(Inventory.location_id == face.location_id)).all()
    )
    pallets = reserve_pallets(session, sku.id)
    reserve_qty = sum(p.qty for p in pallets)
    open_task = session.exec(
        select(ReplenishmentTask).where(
            ReplenishmentTask.to_location_id == face.location_id,
            col(ReplenishmentTask.status).in_(OPEN_REPLENISHMENT_STATUSES),
        )
    ).first()

    return StockReport(
        sku=SkuInfo(
            sku_code=sku.sku_code,
            description=sku.description,
            category=sku.category,
            uom=sku.uom,
            case_qty=sku.case_qty,
        ),
        pick_face=PickFaceStock(
            location=location.code,
            on_hand=on_hand,
            min_qty=face.min_qty,
            max_qty=face.max_qty,
        ),
        reserve_pallets=pallets,
        reserve_qty=reserve_qty,
        total_qty=on_hand + reserve_qty,
        open_task_id=open_task.id if open_task else None,
    )
