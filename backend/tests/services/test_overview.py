from datetime import timedelta

from sqlmodel import Session

from tests.conftest import AS_OF
from warehouse_ops.services.floor_map import get_floor_map
from warehouse_ops.services.overview import HOURS, get_overview
from warehouse_ops.services.picking import list_short_picks


def test_face_counts_match_the_floor_map(session: Session) -> None:
    overview = get_overview(session, now=AS_OF)
    floor = get_floor_map(session)

    assert overview.empty_faces == floor.counts["empty"]
    assert overview.low_faces == floor.counts["low"]
    assert sum(z.empty for z in overview.zones) == overview.empty_faces
    assert sum(z.ok + z.low + z.empty + z.unassigned for z in overview.zones) == 400


def test_short_picks_are_bucketed_by_hour_and_zone(session: Session) -> None:
    overview = get_overview(session, now=AS_OF)
    last_day = list_short_picks(
        session, now=AS_OF, since=AS_OF - timedelta(hours=HOURS), limit=10_000
    )

    assert len(overview.short_picks_by_hour) == HOURS
    assert overview.short_picks_by_hour[-1].hour_start == AS_OF.replace(minute=0)
    assert sum(b.short_picks for b in overview.short_picks_by_hour) == overview.short_picks_24h
    assert sum(z.short_picks for z in overview.zones) == overview.short_picks_24h
    assert overview.short_picks_24h <= len(last_day)  # the window starts on the hour


def test_task_and_count_totals(session: Session) -> None:
    overview = get_overview(session, now=AS_OF)

    assert overview.tasks_awaiting_approval + overview.tasks_approved == 2  # seeded open tasks
    assert overview.open_discrepancies >= 0


def test_urgent_needs_skip_faces_that_already_have_a_task(session: Session) -> None:
    overview = get_overview(session, now=AS_OF)

    assert overview.urgent_needs
    assert all(n.open_task_id is None for n in overview.urgent_needs)
    assert overview.urgent_needs[0].on_hand == 0  # empty faces come first
