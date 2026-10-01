from collections import Counter

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from tests.conftest import AS_OF, make_memory_engine
from warehouse_ops.db.catalog import CATEGORIES
from warehouse_ops.db.models import (
    Inventory,
    Location,
    LocationType,
    Order,
    OrderLine,
    OrderStatus,
    PickFace,
    PickTask,
    PickTaskStatus,
    ReplenishmentStatus,
    ReplenishmentTask,
    Sku,
)
from warehouse_ops.db.seed import SeedSummary, seed_database


def test_summary_counts(seeded: tuple[Engine, SeedSummary]) -> None:
    summary = seeded[1]
    assert summary.skus == 300
    assert summary.pick_faces == 300
    assert summary.below_min_faces == 12
    assert summary.stockouts == 3
    assert summary.replenishment_tasks == 17
    assert summary.short_picks >= summary.below_min_faces
    assert summary.late_orders > 0


def test_layout(session: Session) -> None:
    by_type = Counter(loc.type for loc in session.exec(select(Location)))
    assert by_type[LocationType.PICK] == 400
    assert by_type[LocationType.RESERVE] == 800
    assert by_type[LocationType.STAGING] == 6


def test_every_sku_has_one_pick_face_in_its_zone(session: Session) -> None:
    rows = session.exec(
        select(Sku, PickFace, Location)
        .join(PickFace, col(PickFace.sku_id) == col(Sku.id))
        .join(Location, col(Location.id) == col(PickFace.location_id))
    ).all()
    assert len(rows) == 300
    for sku, face, location in rows:
        assert location.type == LocationType.PICK
        assert location.zone == CATEGORIES[sku.category].zone
        assert 1 <= face.min_qty < face.max_qty


def test_pick_stock_has_no_lpn_and_reserve_pallets_do(session: Session) -> None:
    for inv, location in session.exec(
        select(Inventory, Location).join(Location, col(Location.id) == col(Inventory.location_id))
    ):
        if location.type == LocationType.PICK:
            assert inv.lpn is None
        else:
            assert location.type == LocationType.RESERVE
            assert inv.lpn is not None and inv.lpn.startswith("LPN")
            assert inv.qty > 0


def test_reserve_slots_hold_at_most_one_pallet(session: Session) -> None:
    pallets = session.exec(select(Inventory).where(col(Inventory.lpn).is_not(None))).all()
    per_slot = Counter(p.location_id for p in pallets)
    assert max(per_slot.values()) == 1


def test_below_min_faces_match_planted_problems(session: Session) -> None:
    below_min = session.exec(
        select(PickFace)
        .join(Inventory, col(Inventory.location_id) == col(PickFace.location_id))
        .where(col(Inventory.qty) < col(PickFace.min_qty))
    ).all()
    assert len(below_min) == 12

    without_reserve = [
        face
        for face in below_min
        if not session.exec(
            select(Inventory).where(
                Inventory.sku_id == face.sku_id, col(Inventory.lpn).is_not(None)
            )
        ).first()
    ]
    assert len(without_reserve) == 3  # the planted stockouts


def test_short_picks_are_consistent(session: Session) -> None:
    for task in session.exec(select(PickTask)):
        if task.status == PickTaskStatus.OPEN:
            assert task.picked_qty is None and task.completed_at is None
            assert task.picker_id is None
        else:
            assert task.completed_at is not None and task.completed_at <= AS_OF
            assert task.picker_id is not None
            assert task.picked_qty is not None
            if task.status == PickTaskStatus.SHORT:
                assert task.picked_qty < task.expected_qty
            else:
                assert task.picked_qty == task.expected_qty


def test_every_below_min_face_had_a_short_pick_in_last_24h(session: Session) -> None:
    below_min_locations = set(
        session.exec(
            select(PickFace.location_id)
            .join(Inventory, col(Inventory.location_id) == col(PickFace.location_id))
            .where(col(Inventory.qty) < col(PickFace.min_qty))
        ).all()
    )
    short_locations = {
        t.location_id
        for t in session.exec(select(PickTask).where(PickTask.status == PickTaskStatus.SHORT))
        if t.completed_at is not None and (AS_OF - t.completed_at).total_seconds() <= 24 * 3600
    }
    assert below_min_locations <= short_locations


def test_orders_are_in_the_past_and_late_orders_exist(session: Session) -> None:
    orders = session.exec(select(Order)).all()
    assert all(o.created_at <= AS_OF for o in orders)
    late = [o for o in orders if o.status != OrderStatus.SHIPPED and o.ship_by < AS_OF]
    assert late
    assert all(o.status in (OrderStatus.OPEN, OrderStatus.IN_PROGRESS) for o in late)


def test_order_lines_have_one_pick_task_each(session: Session) -> None:
    lines = session.exec(select(OrderLine)).all()
    tasks = session.exec(select(PickTask)).all()
    assert sorted(t.order_line_id for t in tasks) == sorted(
        line.id for line in lines if line.id is not None
    )


def test_open_replenishment_tasks_target_below_min_faces(session: Session) -> None:
    open_tasks = session.exec(
        select(ReplenishmentTask).where(ReplenishmentTask.status == ReplenishmentStatus.APPROVED)
    ).all()
    assert len(open_tasks) == 2
    for task in open_tasks:
        face = session.get(PickFace, task.to_location_id)
        assert face is not None and face.sku_id == task.sku_id
        stock = session.exec(
            select(Inventory).where(Inventory.location_id == task.to_location_id)
        ).one()
        assert stock.qty < face.min_qty
        assert stock.qty + task.qty <= face.max_qty


def _snapshot(engine: Engine) -> list[tuple[object, ...]]:
    with Session(engine) as session:
        skus = [(s.sku_code, s.description, s.case_qty) for s in session.exec(select(Sku))]
        stock = [(i.location_id, i.lpn, i.qty) for i in session.exec(select(Inventory))]
        orders = [(o.order_number, o.customer, o.status) for o in session.exec(select(Order))]
        return [*skus, *stock, *orders]


def test_same_seed_gives_same_data(seeded: tuple[Engine, SeedSummary]) -> None:
    again = make_memory_engine()
    seed_database(again, seed=42, as_of=AS_OF)
    assert _snapshot(again) == _snapshot(seeded[0])


def test_different_seed_gives_different_data(seeded: tuple[Engine, SeedSummary]) -> None:
    other = make_memory_engine()
    seed_database(other, seed=7, as_of=AS_OF)
    assert _snapshot(other) != _snapshot(seeded[0])


def test_foreign_keys_are_enforced() -> None:
    engine = make_memory_engine()
    seed_database(engine, seed=1, as_of=AS_OF)
    with Session(engine) as session:
        session.add(PickFace(location_id=999_999, sku_id=999_999, min_qty=1, max_qty=2))
        with pytest.raises(IntegrityError):
            session.commit()
