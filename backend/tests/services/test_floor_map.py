from collections import Counter

from sqlmodel import Session

from warehouse_ops.services.floor_map import get_floor_map
from warehouse_ops.services.replenishment import list_replenishment_needs


def test_every_bay_has_a_pick_face_and_two_reserve_slots(session: Session) -> None:
    floor = get_floor_map(session)
    assert len(floor.bays) == 400
    assert len(floor.staging) == 6
    for bay in floor.bays:
        assert bay.pick.location.endswith("-1")
        assert [r.level for r in bay.reserve] == [2, 3]


def test_counts_match_statuses(session: Session) -> None:
    floor = get_floor_map(session)
    statuses = Counter(b.pick.status for b in floor.bays)
    assert all(floor.counts[status] == statuses[status] for status in floor.counts)
    assert floor.counts["unassigned"] == 100  # 400 pick faces, 300 SKUs
    assert sum(floor.counts.values()) == 400


def test_low_and_empty_faces_match_replenishment_needs(session: Session) -> None:
    floor = get_floor_map(session)
    flagged = {b.pick.location for b in floor.bays if b.pick.status in ("low", "empty")}
    below_min = {n.location for n in list_replenishment_needs(session, include_open_demand=False)}
    assert flagged == below_min


def test_open_tasks_and_pallets_are_shown(session: Session) -> None:
    floor = get_floor_map(session)
    assert sum(1 for b in floor.bays if b.pick.open_task_id) == 2  # seeded open tasks
    pallets = [r for b in floor.bays for r in b.reserve if r.lpn]
    assert pallets and all(r.qty > 0 and r.sku_code for r in pallets)
    unassigned = next(b for b in floor.bays if b.pick.status == "unassigned")
    assert unassigned.pick.sku_code is None and unassigned.pick.min_qty is None
