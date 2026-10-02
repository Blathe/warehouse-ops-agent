import pytest
from sqlmodel import Session, col, select

from warehouse_ops.db.models import Inventory, PickFace, ReplenishmentStatus, ReplenishmentTask, Sku
from warehouse_ops.services.errors import NotFoundError
from warehouse_ops.services.inventory import find_stock


def test_find_stock_reports_pick_face_and_pallets(session: Session) -> None:
    sku = session.exec(select(Sku).order_by(col(Sku.sku_code))).first()
    assert sku is not None

    report = find_stock(session, sku.sku_code)

    assert report.sku.sku_code == sku.sku_code
    face = session.exec(select(PickFace).where(PickFace.sku_id == sku.id)).one()
    assert (report.pick_face.min_qty, report.pick_face.max_qty) == (face.min_qty, face.max_qty)

    stored = session.exec(select(Inventory).where(Inventory.sku_id == sku.id)).all()
    assert report.total_qty == sum(i.qty for i in stored)
    assert report.reserve_qty == sum(p.qty for p in report.reserve_pallets)
    received = [p.received_at for p in report.reserve_pallets]
    assert received == sorted(received)  # FIFO


def test_find_stock_trims_whitespace(session: Session) -> None:
    sku = session.exec(select(Sku)).first()
    assert sku is not None
    assert find_stock(session, f" {sku.sku_code} ").sku.sku_code == sku.sku_code


def test_unknown_sku_raises_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError, match="00000"):
        find_stock(session, "00000")


def test_find_stock_reports_an_open_replenishment_task(session: Session) -> None:
    task = session.exec(
        select(ReplenishmentTask).where(ReplenishmentTask.status == ReplenishmentStatus.APPROVED)
    ).first()
    assert task is not None  # the seed plants open tasks
    sku = session.get(Sku, task.sku_id)
    assert sku is not None

    assert find_stock(session, sku.sku_code).open_task_id == task.id


def test_find_stock_has_no_open_task_when_none_is_open(session: Session) -> None:
    open_skus = {
        t.sku_id
        for t in session.exec(
            select(ReplenishmentTask).where(
                col(ReplenishmentTask.status).in_(
                    [ReplenishmentStatus.PROPOSED, ReplenishmentStatus.APPROVED]
                )
            )
        )
    }
    sku = session.exec(select(Sku).where(col(Sku.id).not_in(open_skus))).first()
    assert sku is not None

    assert find_stock(session, sku.sku_code).open_task_id is None
