from collections import defaultdict

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from tests.conftest import AS_OF, make_memory_engine
from warehouse_ops.db.history import SCENARIOS, TRANSIENT_SCENARIOS
from warehouse_ops.db.models import (
    Inventory,
    InventoryTxn,
    Location,
    PickTask,
    PickTaskStatus,
    ReplenishmentStatus,
    ReplenishmentTask,
    ShelfVariance,
    Sku,
    TxnType,
)
from warehouse_ops.db.seed import SeedSummary, seed_database


def ledger_matches_inventory(session: Session) -> bool:
    totals: dict[tuple[int, int], int] = defaultdict(int)
    for txn in session.exec(select(InventoryTxn)):
        totals[(txn.location_id, txn.sku_id)] += txn.qty_change
    stock = {(i.location_id, i.sku_id): i.qty for i in session.exec(select(Inventory))}
    return all(totals.get(key, 0) == stock.get(key, 0) for key in set(totals) | set(stock))


def variances(session: Session, scenario: str) -> list[ShelfVariance]:
    return list(session.exec(select(ShelfVariance).where(ShelfVariance.scenario == scenario)))


def stock_at(session: Session, location_id: int, sku_id: int) -> Inventory | None:
    return session.exec(
        select(Inventory).where(Inventory.location_id == location_id, Inventory.sku_id == sku_id)
    ).first()


def test_ledger_explains_every_quantity(session: Session) -> None:
    assert ledger_matches_inventory(session)
    openings = session.exec(select(InventoryTxn).where(InventoryTxn.type == TxnType.OPENING))
    assert all(t.qty_change > 0 for t in openings)
    assert all(t.user for t in session.exec(select(InventoryTxn)))


def test_ledger_records_picks_and_replenishments(session: Session) -> None:
    picked = session.exec(
        select(PickTask).where(PickTask.status != PickTaskStatus.OPEN, col(PickTask.picked_qty) > 0)
    ).all()
    pick_refs = {
        t.ref for t in session.exec(select(InventoryTxn).where(InventoryTxn.type == TxnType.PICK))
    }
    assert {f"pick_task:{t.id}" for t in picked} <= pick_refs

    done = session.exec(
        select(ReplenishmentTask).where(ReplenishmentTask.status == ReplenishmentStatus.DONE)
    ).all()
    for task in done:
        moves = session.exec(
            select(InventoryTxn).where(InventoryTxn.ref == f"replenishment_task:{task.id}")
        ).all()
        assert sorted((m.type, m.qty_change) for m in moves) == [
            (TxnType.REPLEN_IN, task.qty),
            (TxnType.REPLEN_OUT, -task.qty),
        ]


def test_every_scenario_is_planted_once_in_its_own_bay(
    seeded: tuple[Engine, SeedSummary], session: Session
) -> None:
    rows = session.exec(select(ShelfVariance)).all()
    assert {r.scenario for r in rows} == set(SCENARIOS)
    assert seeded[1].planted_discrepancies == len(rows) == 8  # mis_slot and short_replen use 2
    assert all(r.transient == (r.scenario in TRANSIENT_SCENARIOS) for r in rows)

    bays: dict[str, set[tuple[str, int, int]]] = defaultdict(set)
    for row in rows:
        loc = session.get(Location, row.location_id)
        assert loc is not None
        bays[row.scenario].add((loc.zone, loc.aisle, loc.bay))
    all_bays = [b for scenario_bays in bays.values() for b in scenario_bays]
    assert len(all_bays) == len(set(all_bays))  # no two scenarios share a bay


def test_blank_adjustment_is_the_only_blank_reason(session: Session) -> None:
    (variance,) = variances(session, "blank_adjustment")
    blank = session.exec(
        select(InventoryTxn).where(
            InventoryTxn.type == TxnType.ADJUSTMENT, InventoryTxn.reason == ""
        )
    ).all()
    assert len(blank) == 1
    assert blank[0].location_id == variance.location_id
    assert blank[0].qty_change == -variance.delta > 0
    # Other adjustments exist, with reasons, so the blank one isn't the only adjustment.
    others = session.exec(
        select(InventoryTxn).where(
            InventoryTxn.type == TxnType.ADJUSTMENT, InventoryTxn.reason != ""
        )
    ).all()
    assert len(others) >= 5


def test_mis_slot_moves_a_whole_pallet_to_an_empty_neighbour(session: Session) -> None:
    gone, found = sorted(variances(session, "mis_slot"), key=lambda v: v.delta)
    assert gone.lpn == found.lpn and gone.delta == -found.delta < 0
    pallet = stock_at(session, gone.location_id, gone.sku_id)
    assert pallet is not None and pallet.qty == found.delta
    assert stock_at(session, found.location_id, found.sku_id) is None
    here, there = session.get(Location, gone.location_id), session.get(Location, found.location_id)
    assert here and there
    assert (here.aisle, here.level) == (there.aisle, there.level) and abs(here.bay - there.bay) == 1


def test_case_vs_each_counts_cases(session: Session) -> None:
    (variance,) = variances(session, "case_vs_each")
    pallet = stock_at(session, variance.location_id, variance.sku_id)
    sku = session.get(Sku, variance.sku_id)
    assert pallet is not None and sku is not None
    assert pallet.qty + variance.delta == pallet.qty // sku.case_qty


def test_short_replen_leaves_the_difference_on_the_pallet(session: Session) -> None:
    face, pallet = sorted(variances(session, "short_replen"), key=lambda v: v.delta)
    assert face.delta == -pallet.delta < 0 and pallet.lpn is not None
    task = session.exec(
        select(ReplenishmentTask).where(
            ReplenishmentTask.lpn == pallet.lpn,
            ReplenishmentTask.to_location_id == face.location_id,
            ReplenishmentTask.status == ReplenishmentStatus.DONE,
        )
    ).first()
    assert task is not None and task.qty > -face.delta


def test_mid_pick_count_matches_an_open_pick(session: Session) -> None:
    (variance,) = variances(session, "mid_pick_count")
    open_picks = session.exec(
        select(PickTask).where(
            PickTask.location_id == variance.location_id, PickTask.status == PickTaskStatus.OPEN
        )
    ).all()
    assert -variance.delta in {t.expected_qty for t in open_picks}


def test_unexplained_shrink_has_no_evidence(session: Session) -> None:
    (variance,) = variances(session, "unexplained_shrink")
    assert 2 <= -variance.delta <= 6
    adjustments = session.exec(
        select(InventoryTxn).where(
            InventoryTxn.location_id == variance.location_id,
            InventoryTxn.type == TxnType.ADJUSTMENT,
        )
    ).all()
    assert adjustments == []


def test_history_is_deterministic(seeded: tuple[Engine, SeedSummary]) -> None:
    def snapshot(engine: Engine) -> list[tuple[object, ...]]:
        with Session(engine) as session:
            txns = session.exec(select(InventoryTxn).order_by(col(InventoryTxn.id))).all()
            truth = session.exec(select(ShelfVariance).order_by(col(ShelfVariance.id))).all()
            return [(t.ts, t.location_id, t.qty_change, t.type, t.user, t.reason) for t in txns] + [
                (v.location_id, v.delta, v.scenario) for v in truth
            ]

    again = make_memory_engine()
    seed_database(again, seed=42, as_of=AS_OF)
    assert snapshot(again) == snapshot(seeded[0])
