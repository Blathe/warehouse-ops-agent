from datetime import timedelta

from sqlmodel import Session

from tests.conftest import AS_OF
from warehouse_ops.services.picking import list_short_picks


def test_defaults_to_last_24_hours_newest_first(session: Session) -> None:
    shorts = list_short_picks(session, now=AS_OF)
    assert shorts
    assert all(AS_OF - timedelta(hours=24) <= s.completed_at <= AS_OF for s in shorts)
    assert [s.completed_at for s in shorts] == sorted(
        (s.completed_at for s in shorts), reverse=True
    )
    for s in shorts:
        assert s.picked_qty < s.expected_qty
        assert s.short_qty == s.expected_qty - s.picked_qty


def test_since_widens_the_window(session: Session) -> None:
    last_day = list_short_picks(session, now=AS_OF)
    all_time = list_short_picks(session, now=AS_OF, since=AS_OF - timedelta(days=5))
    assert len(all_time) >= len(last_day)
    assert {s.task_id for s in last_day} <= {s.task_id for s in all_time}


def test_filters_by_zone_and_sku(session: Session) -> None:
    zone_a = list_short_picks(session, now=AS_OF, zone="a")
    assert zone_a and all(s.zone == "A" for s in zone_a)

    sku_code = zone_a[0].sku_code
    for_sku = list_short_picks(session, now=AS_OF, sku_code=sku_code)
    assert for_sku and all(s.sku_code == sku_code for s in for_sku)


def test_nothing_before_the_data_starts(session: Session) -> None:
    assert list_short_picks(session, now=AS_OF - timedelta(days=30)) == []
