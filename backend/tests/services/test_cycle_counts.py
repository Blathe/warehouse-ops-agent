"""Simulated cycle counts, and accepting or recounting the discrepancies they open.

The ``session`` fixture never commits, so every count and adjustment is rolled back.
"""

from random import Random

import pytest
from sqlmodel import Session, select

from tests.conftest import AS_OF
from tests.db.test_history import ledger_matches_inventory
from warehouse_ops.db.models import (
    CountStatus,
    CycleCount,
    Inventory,
    InventoryTxn,
    Location,
    PickTask,
    PickTaskStatus,
    ShelfVariance,
    TxnType,
)
from warehouse_ops.services.cycle_counts import (
    CycleCountOut,
    accept_cycle_count,
    list_cycle_counts,
    request_recount,
    simulate_cycle_count,
)
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.floor_map import get_floor_map


def count(session: Session, seed: int = 1) -> list[CycleCountOut]:
    return simulate_cycle_count(session, rng=Random(seed), now=AS_OF).discrepancies


def at(discrepancies: list[CycleCountOut], scenario: str, session: Session) -> CycleCountOut:
    """The discrepancy opened by a planted scenario (the lowest variance if it has two)."""
    rows = session.exec(select(ShelfVariance).where(ShelfVariance.scenario == scenario)).all()
    codes = {loc.code for row in rows if (loc := session.get(Location, row.location_id))}
    return min((d for d in discrepancies if d.location in codes), key=lambda d: d.variance)


def accept(session: Session, found: CycleCountOut, reason: str = "Recounted, it's right") -> None:
    accept_cycle_count(session, count_id=found.id, decided_by="Pat", reason=reason, now=AS_OF)


def test_a_count_finds_every_planted_problem_among_matching_locations(session: Session) -> None:
    run = simulate_cycle_count(session, rng=Random(1), now=AS_OF)
    assert run.counted == 30
    assert len(run.discrepancies) == 8  # six scenarios; mis_slot and short_replen open two each
    assert run.matched == 22
    assert all(d.variance == d.counted_qty - d.system_qty != 0 for d in run.discrepancies)
    matched = session.exec(select(CycleCount).where(CycleCount.status == CountStatus.MATCHED)).all()
    assert len(matched) == 22 and all(c.variance == 0 for c in matched)


def test_variances_tell_the_story(session: Session) -> None:
    found = count(session)
    case = at(found, "case_vs_each", session)
    assert case.counted_qty * case.case_qty == case.system_qty  # counted in cases
    missing, extra = sorted(
        (d for d in found if d.lpn and d.lpn == at(found, "mis_slot", session).lpn),
        key=lambda d: d.variance,
    )
    assert (
        missing.counted_qty == 0 and extra.system_qty == 0 and extra.variance == -missing.variance
    )


def test_open_discrepancies_are_not_counted_twice(session: Session) -> None:
    count(session)
    second = simulate_cycle_count(session, rng=Random(2), now=AS_OF)
    assert second.discrepancies == []  # the planted problems are already open
    assert len(list_cycle_counts(session, [CountStatus.DISCREPANCY])) == 8


def test_accepting_adjusts_the_system_and_the_ledger(session: Session) -> None:
    blank = at(count(session), "blank_adjustment", session)
    face = session.exec(
        select(Inventory).join(Location).where(Location.code == blank.location)
    ).one()
    before = face.qty

    accept(session, blank, "Bad adjustment by Kim, reversed")

    assert face.qty == before + blank.variance
    adjustment = session.exec(
        select(InventoryTxn).where(InventoryTxn.ref == f"cycle_count:{blank.id}")
    ).one()
    assert adjustment.type == TxnType.COUNT_ADJUSTMENT
    assert (adjustment.qty_change, adjustment.user) == (blank.variance, "Pat")
    assert adjustment.reason == "Bad adjustment by Kim, reversed"
    assert ledger_matches_inventory(session)
    stored = session.get(CycleCount, blank.id)
    assert stored is not None and stored.status == CountStatus.ACCEPTED
    # The shelf now matches the system, so the next count of it matches.
    assert (
        session.exec(
            select(ShelfVariance).where(ShelfVariance.scenario == "blank_adjustment")
        ).first()
        is None
    )


def test_a_reason_is_required_and_a_count_is_resolved_once(session: Session) -> None:
    shrink = at(count(session), "unexplained_shrink", session)
    with pytest.raises(RuleViolationError, match="reason"):
        accept(session, shrink, "  ")
    accept(session, shrink)
    with pytest.raises(RuleViolationError, match="not an open discrepancy"):
        accept(session, shrink)
    with pytest.raises(NotFoundError):
        request_recount(session, count_id=999_999, decided_by="Pat", now=AS_OF)


def test_a_mis_slotted_pallet_moves_when_both_counts_are_accepted(session: Session) -> None:
    found = count(session)
    missing = at(found, "mis_slot", session)
    extra = next(d for d in found if d.lpn == missing.lpn and d.id != missing.id)

    with pytest.raises(RuleViolationError, match="still recorded"):
        accept(session, extra)  # the pallet can't be in two places
    accept(session, missing)
    accept(session, extra)

    pallet = session.exec(select(Inventory).where(Inventory.lpn == missing.lpn)).one()
    location = session.get(Location, pallet.location_id)
    assert location is not None and location.code == extra.location
    assert ledger_matches_inventory(session)


def test_recounts_clear_counting_mistakes_and_confirm_the_pick(session: Session) -> None:
    found = count(session)
    case = at(found, "case_vs_each", session)
    mid_pick = at(found, "mid_pick_count", session)
    shrink = at(found, "unexplained_shrink", session)
    for d in (case, mid_pick, shrink):
        request_recount(session, count_id=d.id, decided_by="Pat", now=AS_OF)

    again = simulate_cycle_count(session, rng=Random(2), now=AS_OF)

    reopened = {d.location for d in again.discrepancies}
    assert reopened == {shrink.location}  # real loss shows up again; the artefacts don't
    for d in (case, mid_pick, shrink):
        old = session.get(CycleCount, d.id)
        assert old is not None and old.status == CountStatus.RECOUNTED
    confirmed = session.exec(
        select(PickTask)
        .join(Location)
        .where(Location.code == mid_pick.location, PickTask.status == PickTaskStatus.PICKED)
        .where(PickTask.completed_at == AS_OF)
    ).first()
    assert confirmed is not None and confirmed.picked_qty == -mid_pick.variance
    assert ledger_matches_inventory(session)


def test_accepting_a_miscount_leaves_the_real_stock_behind(session: Session) -> None:
    case = at(count(session), "case_vs_each", session)
    accept(session, case, "Counted, trust it")  # wrong: the clerk counted cases

    again = simulate_cycle_count(session, rng=Random(3), now=AS_OF)

    (overage,) = [d for d in again.discrepancies if d.location == case.location]
    assert overage.variance == -case.variance  # the units are still on the shelf


def test_the_floor_map_marks_bays_with_open_counts(session: Session) -> None:
    found = count(session)
    marked = {code for bay in get_floor_map(session).bays for code in bay.open_discrepancies}
    assert marked == {d.location for d in found}
