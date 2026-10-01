from sqlmodel import Session, col, select

from warehouse_ops.db.models import (
    Inventory,
    PickFace,
    ReplenishmentStatus,
    ReplenishmentTask,
    Sku,
)
from warehouse_ops.services.replenishment import list_replenishment_needs


def test_every_below_min_face_is_listed(session: Session) -> None:
    below_min_skus = set(
        session.exec(
            select(Sku.sku_code)
            .join(PickFace, col(PickFace.sku_id) == col(Sku.id))
            .join(Inventory, col(Inventory.location_id) == col(PickFace.location_id))
            .where(col(Inventory.qty) <= col(PickFace.min_qty))
        ).all()
    )
    needs = list_replenishment_needs(session, include_open_demand=False)
    assert {n.sku_code for n in needs} == below_min_skus
    assert all(n.on_hand <= n.min_qty for n in needs)


def test_open_demand_adds_faces(session: Session) -> None:
    with_demand = list_replenishment_needs(session)
    without = list_replenishment_needs(session, include_open_demand=False)
    assert len(with_demand) >= len(without)
    for need in with_demand:
        if "below open pick demand" in need.reasons:
            assert need.on_hand < need.open_demand


def test_empty_faces_come_first(session: Session) -> None:
    needs = list_replenishment_needs(session)
    empties = [n.on_hand == 0 for n in needs]
    assert empties == sorted(empties, reverse=True)


def test_suggested_qty_is_whole_cases_within_max_and_source(session: Session) -> None:
    case_qty = {s.sku_code: s.case_qty for s in session.exec(select(Sku))}
    for need in list_replenishment_needs(session):
        if need.source is None:
            assert need.suggested_qty == 0  # nothing in reserve to move
            continue
        assert need.suggested_qty > 0
        assert need.on_hand + need.suggested_qty <= need.max_qty
        assert need.suggested_qty <= need.source.qty
        if need.suggested_qty < need.source.qty:
            assert need.suggested_qty % case_qty[need.sku_code] == 0


def test_stockouts_have_no_source(session: Session) -> None:
    no_source = [n for n in list_replenishment_needs(session) if n.source is None]
    assert len(no_source) == 3  # the planted stockouts


def test_open_tasks_are_linked(session: Session) -> None:
    open_task_ids = set(
        session.exec(
            select(ReplenishmentTask.id).where(
                ReplenishmentTask.status == ReplenishmentStatus.APPROVED
            )
        ).all()
    )
    linked = {n.open_task_id for n in list_replenishment_needs(session) if n.open_task_id}
    assert linked == open_task_ids


def test_zone_filter(session: Session) -> None:
    needs = list_replenishment_needs(session, zone="b")
    assert needs and all(n.zone == "B" for n in needs)
