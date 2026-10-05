import json
from random import Random

import pytest
from pydantic import BaseModel
from sqlmodel import Session

from tests.conftest import AS_OF
from warehouse_ops.db.models import TxnType
from warehouse_ops.services.cycle_counts import simulate_cycle_count
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.inventory import find_stock
from warehouse_ops.services.ledger import get_inventory_history, get_nearby_stock, list_open_picks

BLANK_ADJUSTMENT_FACE = "A-02-23-1"  # planted by the seed (see db/history.py)
MIS_SLOT = ("A-04-21-3", "A-04-22-3")
MID_PICK_FACE = "A-04-02-1"


def test_history_is_oldest_first_with_running_balances(session: Session) -> None:
    rows = get_inventory_history(session, location=BLANK_ADJUSTMENT_FACE)
    assert rows[0].type == TxnType.OPENING
    assert [r.ts for r in rows] == sorted(r.ts for r in rows)
    running = 0
    for row in rows:
        running += row.qty_change
        assert row.balance_after == running
    stock = find_stock(session, rows[0].sku_code)
    assert rows[-1].balance_after == stock.pick_face.on_hand  # the ledger ends at the system qty


def test_history_shows_the_blank_adjustment(session: Session) -> None:
    rows = get_inventory_history(
        session, location=BLANK_ADJUSTMENT_FACE, txn_type=TxnType.ADJUSTMENT
    )
    assert [(r.qty_change, r.reason) for r in rows] == [(30, "")]
    by_user = get_inventory_history(session, user=rows[0].user.split()[0].lower())
    assert any(r.location == BLANK_ADJUSTMENT_FACE for r in by_user)


def test_history_needs_a_filter_and_honours_limit(session: Session) -> None:
    with pytest.raises(RuleViolationError):
        get_inventory_history(session)
    assert len(get_inventory_history(session, location=BLANK_ADJUSTMENT_FACE, limit=3)) == 3
    with pytest.raises(NotFoundError):
        get_inventory_history(session, location="Z-99-99-9")


def test_nearby_stock_shows_the_empty_slot_and_counts(session: Session) -> None:
    simulate_cycle_count(session, rng=Random(1), now=AS_OF)
    slots = {s.location: s for s in get_nearby_stock(session, MIS_SLOT[0], bays=1)}
    assert slots[MIS_SLOT[0]].lpn is not None
    assert slots[MIS_SLOT[1]].sku_code is None and slots[MIS_SLOT[1]].qty == 0
    found = slots[MIS_SLOT[1]].last_count
    assert found is not None and found.counted_qty == slots[MIS_SLOT[0]].qty
    assert {s.location[:7] for s in slots.values()} == {"A-04-20", "A-04-21", "A-04-22"}


def test_open_picks(session: Session) -> None:
    picks = list_open_picks(session, MID_PICK_FACE)
    assert picks and all(p.expected_qty > 0 for p in picks)


def test_nothing_reveals_the_hidden_truth(session: Session) -> None:
    simulate_cycle_count(session, rng=Random(1), now=AS_OF)
    rows: list[BaseModel] = [
        *get_inventory_history(session, location=BLANK_ADJUSTMENT_FACE),
        *get_nearby_stock(session, MIS_SLOT[0]),
        *list_open_picks(session, MID_PICK_FACE),
    ]
    text = json.dumps([row.model_dump(mode="json") for row in rows])
    for word in ("blank_adjustment", "mis_slot", "case_vs_each", "shelf", "scenario"):
        assert word not in text
