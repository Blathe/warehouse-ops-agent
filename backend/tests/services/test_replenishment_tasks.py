"""Rules for creating and deciding replenishment tasks.

The ``session`` fixture never commits, so every write here is rolled back after the test.
"""

from typing import Any

import pytest
from sqlmodel import Session, select

from tests.conftest import AS_OF
from tests.db.test_history import ledger_matches_inventory
from warehouse_ops.db.models import (
    Inventory,
    InventoryTxn,
    Location,
    LocationType,
    ReplenishmentStatus,
    ReplenishmentTask,
    TxnType,
)
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.inventory import find_stock
from warehouse_ops.services.replenishment import list_replenishment_needs
from warehouse_ops.services.replenishment_tasks import (
    CREW,
    complete_next_replenishment_task,
    create_replenishment_task,
    decide_replenishment_task,
    get_replenishment_task,
    list_replenishment_tasks,
)
from warehouse_ops.services.schemas import ReplenishmentNeed


def _actionable_need(session: Session) -> ReplenishmentNeed:
    """A face that needs stock, has a reserve pallet and no open task."""
    return next(
        n
        for n in list_replenishment_needs(session)
        if n.source is not None and n.open_task_id is None and n.suggested_qty > 0
    )


def _valid_args(need: ReplenishmentNeed, **overrides: Any) -> dict[str, Any]:
    assert need.source is not None
    args: dict[str, Any] = {
        "sku_code": need.sku_code,
        "from_location": need.source.location,
        "to_location": need.location,
        "qty": need.suggested_qty,
        "reason": "Pick face empty",
        "created_by": "test",
        "now": AS_OF,
    }
    return args | overrides


def test_creates_a_proposed_task(session: Session) -> None:
    need = _actionable_need(session)
    task = create_replenishment_task(session, **_valid_args(need))

    assert task.status == ReplenishmentStatus.PROPOSED
    assert (task.sku_code, task.to_location, task.qty) == (
        need.sku_code,
        need.location,
        need.suggested_qty,
    )
    assert need.source is not None and task.lpn == need.source.lpn
    assert task.created_at == AS_OF and task.approved_by is None
    assert get_replenishment_task(session, task.task_id) == task

    # The face now shows the open task, so it won't be suggested twice.
    again = next(n for n in list_replenishment_needs(session) if n.location == need.location)
    assert again.open_task_id == task.task_id


def test_codes_are_trimmed_and_case_insensitive(session: Session) -> None:
    need = _actionable_need(session)
    assert need.source is not None
    task = create_replenishment_task(
        session,
        **_valid_args(
            need,
            from_location=f" {need.source.location.lower()} ",
            to_location=need.location.lower(),
        ),
    )
    assert task.from_location == need.source.location


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"sku_code": "00000"}, "No SKU"),
        ({"from_location": "Z-99-99-9"}, "No location"),
        ({"to_location": "Z-99-99-9"}, "No location"),
    ],
)
def test_unknown_codes_are_not_found(
    session: Session, override: dict[str, Any], message: str
) -> None:
    with pytest.raises(NotFoundError, match=message):
        create_replenishment_task(session, **_valid_args(_actionable_need(session), **override))


def test_target_must_be_the_skus_pick_face(session: Session) -> None:
    need = _actionable_need(session)
    other_face = next(n for n in list_replenishment_needs(session) if n.location != need.location)
    with pytest.raises(RuleViolationError, match=f"its pick face is {need.location}"):
        create_replenishment_task(session, **_valid_args(need, to_location=other_face.location))


def test_source_must_be_a_reserve_slot(session: Session) -> None:
    need = _actionable_need(session)
    with pytest.raises(RuleViolationError, match="not a reserve slot"):
        create_replenishment_task(session, **_valid_args(need, from_location=need.location))


def test_source_must_hold_the_sku(session: Session) -> None:
    need = _actionable_need(session)
    assert need.source is not None
    other_slot = session.exec(
        select(Location).where(
            Location.type == LocationType.RESERVE, Location.code != need.source.location
        )
    ).first()
    assert other_slot is not None
    with pytest.raises(RuleViolationError, match="holds no stock"):
        create_replenishment_task(session, **_valid_args(need, from_location=other_slot.code))


@pytest.mark.parametrize("qty", [0, -5])
def test_qty_must_be_positive(session: Session, qty: int) -> None:
    with pytest.raises(RuleViolationError, match="greater than 0"):
        create_replenishment_task(session, **_valid_args(_actionable_need(session), qty=qty))


def test_qty_cannot_exceed_the_pallet(session: Session) -> None:
    need = _actionable_need(session)
    assert need.source is not None
    with pytest.raises(RuleViolationError, match=f"only holds {need.source.qty}"):
        create_replenishment_task(session, **_valid_args(need, qty=need.source.qty + 1))


def test_qty_cannot_push_the_face_over_max(session: Session) -> None:
    need = _actionable_need(session)
    room = need.max_qty - need.on_hand
    with pytest.raises(RuleViolationError, match=f"at most {room} can be added"):
        create_replenishment_task(session, **_valid_args(need, qty=room + 1))


def test_no_second_open_task_for_a_face(session: Session) -> None:
    need = _actionable_need(session)
    first = create_replenishment_task(session, **_valid_args(need, qty=1))
    with pytest.raises(RuleViolationError, match=f"Task #{first.task_id} .* already open"):
        create_replenishment_task(session, **_valid_args(need, qty=1))


def test_seeded_open_tasks_block_new_ones(session: Session) -> None:
    blocked = next(n for n in list_replenishment_needs(session) if n.open_task_id is not None)
    assert blocked.source is not None
    with pytest.raises(RuleViolationError, match="already open"):
        create_replenishment_task(session, **_valid_args(blocked, qty=1))


def test_reason_is_required(session: Session) -> None:
    with pytest.raises(RuleViolationError, match="reason"):
        create_replenishment_task(session, **_valid_args(_actionable_need(session), reason="  "))


@pytest.mark.parametrize(
    ("approve", "status"),
    [(True, ReplenishmentStatus.APPROVED), (False, ReplenishmentStatus.REJECTED)],
)
def test_decide_sets_status_and_who(
    session: Session, approve: bool, status: ReplenishmentStatus
) -> None:
    task = create_replenishment_task(session, **_valid_args(_actionable_need(session)))
    decided = decide_replenishment_task(
        session, task_id=task.task_id, approve=approve, decided_by="Pat Supervisor", now=AS_OF
    )
    assert decided.status == status
    assert decided.approved_by == "Pat Supervisor" and decided.decided_at == AS_OF


def test_only_proposed_tasks_can_be_decided(session: Session) -> None:
    task = create_replenishment_task(session, **_valid_args(_actionable_need(session)))
    decide_replenishment_task(
        session, task_id=task.task_id, approve=True, decided_by="Pat", now=AS_OF
    )
    with pytest.raises(RuleViolationError, match="only PROPOSED"):
        decide_replenishment_task(
            session, task_id=task.task_id, approve=False, decided_by="Pat", now=AS_OF
        )


def test_decide_unknown_task(session: Session) -> None:
    with pytest.raises(NotFoundError):
        decide_replenishment_task(
            session, task_id=999_999, approve=True, decided_by="Pat", now=AS_OF
        )


def test_list_returns_every_status_newest_first(session: Session) -> None:
    everything = list_replenishment_tasks(session)

    assert {t.status for t in everything} >= {
        ReplenishmentStatus.APPROVED,
        ReplenishmentStatus.DONE,
    }  # the seed has open and finished tasks
    created = [t.created_at for t in everything]
    assert created == sorted(created, reverse=True)


def test_list_can_be_narrowed_by_status(session: Session) -> None:
    open_statuses = (ReplenishmentStatus.PROPOSED, ReplenishmentStatus.APPROVED)
    active = list_replenishment_tasks(session, open_statuses)
    done = list_replenishment_tasks(session, (ReplenishmentStatus.DONE,))

    assert active and all(t.status in open_statuses for t in active)
    assert done and all(t.status == ReplenishmentStatus.DONE for t in done)
    assert len(active) + len(done) <= len(list_replenishment_tasks(session))


def test_list_includes_a_new_proposal(session: Session) -> None:
    task = create_replenishment_task(session, **_valid_args(_actionable_need(session)))

    active = list_replenishment_tasks(session, (ReplenishmentStatus.PROPOSED,))

    assert [t.task_id for t in active] == [task.task_id]


def test_list_honours_the_limit(session: Session) -> None:
    assert len(list_replenishment_tasks(session, limit=3)) == 3


def _drain(session: Session) -> None:
    """Finish every approved task, so a test starts with none waiting."""
    while complete_next_replenishment_task(session) is not None:
        pass


def _approved(session: Session, **overrides: Any) -> ReplenishmentTask:
    """An approved task built directly, so a test can use a quantity the rules would refuse."""
    need = _actionable_need(session)
    assert need.source is not None
    pallet = session.exec(select(Inventory).where(Inventory.lpn == need.source.lpn)).one()
    face = session.exec(select(Location).where(Location.code == need.location)).one()
    fields: dict[str, Any] = {
        "sku_id": pallet.sku_id,
        "from_location_id": pallet.location_id,
        "to_location_id": face.id,
        "lpn": pallet.lpn,
        "qty": need.suggested_qty,
        "reason": "test",
        "status": ReplenishmentStatus.APPROVED,
        "created_by": "test",
        "approved_by": "Pat",
        "created_at": AS_OF,
        "decided_at": AS_OF,
    }
    task = ReplenishmentTask(**(fields | overrides))
    session.add(task)
    session.flush()
    return task


def test_completing_a_task_moves_the_stock(session: Session) -> None:
    _drain(session)
    need = _actionable_need(session)
    task = create_replenishment_task(session, **_valid_args(need))
    decide_replenishment_task(
        session, task_id=task.task_id, approve=True, decided_by="Pat", now=AS_OF
    )
    before = find_stock(session, need.sku_code)
    assert before.open_task_id == task.task_id

    done = complete_next_replenishment_task(session)

    assert done is not None and done.task_id == task.task_id
    assert done.status == ReplenishmentStatus.DONE
    after = find_stock(session, need.sku_code)
    assert after.pick_face.on_hand == before.pick_face.on_hand + task.qty
    assert after.reserve_qty == before.reserve_qty - task.qty
    assert after.total_qty == before.total_qty  # stock moved; none created or lost
    assert after.open_task_id is None  # the face no longer has an open task


def test_completes_the_oldest_approved_task_first(session: Session) -> None:
    waiting = session.exec(
        select(ReplenishmentTask).where(ReplenishmentTask.status == ReplenishmentStatus.APPROVED)
    ).all()
    assert len(waiting) >= 2  # the seed leaves open tasks
    expected = [t.id for t in sorted(waiting, key=lambda t: (t.decided_at or AS_OF, t.id or 0))]

    finished = []
    while (task := complete_next_replenishment_task(session)) is not None:
        finished.append(task.task_id)

    assert finished == expected


def test_nothing_happens_when_no_task_is_approved(session: Session) -> None:
    _drain(session)
    assert complete_next_replenishment_task(session) is None


def test_a_task_nobody_approved_is_never_completed(session: Session) -> None:
    _drain(session)
    proposed = create_replenishment_task(session, **_valid_args(_actionable_need(session)))

    assert complete_next_replenishment_task(session) is None
    assert get_replenishment_task(session, proposed.task_id).status == ReplenishmentStatus.PROPOSED


def test_an_emptied_pallet_frees_its_slot(session: Session) -> None:
    _drain(session)
    source = _actionable_need(session).source
    assert source is not None
    task = _approved(session, qty=source.qty)  # take the whole pallet

    done = complete_next_replenishment_task(session)

    assert done is not None and done.task_id == task.id
    assert session.exec(select(Inventory).where(Inventory.lpn == task.lpn)).first() is None


def test_a_pallet_that_cannot_cover_the_task_is_an_error(session: Session) -> None:
    _drain(session)
    task = _approved(session, qty=10_000_000)

    with pytest.raises(RuleViolationError, match="no longer holds"):
        complete_next_replenishment_task(session)
    assert get_replenishment_task(session, task.id or 0).status == ReplenishmentStatus.APPROVED


def test_completing_a_task_writes_both_moves_to_the_ledger(session: Session) -> None:
    _drain(session)
    task = _approved(session)

    done = complete_next_replenishment_task(session, AS_OF)

    assert done is not None
    moves = session.exec(
        select(InventoryTxn).where(InventoryTxn.ref == f"replenishment_task:{task.id}")
    ).all()
    assert sorted((m.type, m.location_id, m.qty_change) for m in moves) == sorted(
        [
            (TxnType.REPLEN_OUT, task.from_location_id, -task.qty),
            (TxnType.REPLEN_IN, task.to_location_id, task.qty),
        ]
    )
    assert all(m.ts == AS_OF and m.user == CREW for m in moves)
    assert ledger_matches_inventory(session)  # the ledger still explains every quantity
