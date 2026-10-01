"""Rules for creating and deciding replenishment tasks.

The ``session`` fixture never commits, so every write here is rolled back after the test.
"""

from typing import Any

import pytest
from sqlmodel import Session, select

from tests.conftest import AS_OF
from warehouse_ops.db.models import Location, LocationType, ReplenishmentStatus
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.replenishment import list_replenishment_needs
from warehouse_ops.services.replenishment_tasks import (
    create_replenishment_task,
    decide_replenishment_task,
    get_replenishment_task,
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
