"""The numbers behind the Overview page: what needs a supervisor's attention right now.

Everything here is built from the other services, so a "low" pick face, a short pick or an
open count means exactly what it means on the other pages.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from warehouse_ops.db.models import CycleCount, ReplenishmentStatus, ReplenishmentTask
from warehouse_ops.services.cycle_counts import OPEN_STATUSES as OPEN_COUNT_STATUSES
from warehouse_ops.services.floor_map import get_floor_map
from warehouse_ops.services.picking import list_short_picks
from warehouse_ops.services.replenishment import list_replenishment_needs
from warehouse_ops.services.schemas import LocalDateTime, ReplenishmentNeed

URGENT_NEEDS = 6  # how many pick faces the "needs attention" list shows
HOURS = 24  # the short pick chart covers the last day, one bar per hour


class ZoneHealth(BaseModel):
    zone: str
    ok: int
    low: int
    empty: int
    unassigned: int
    short_picks: int  # in the last 24 hours


class HourBucket(BaseModel):
    hour_start: LocalDateTime
    short_picks: int


class Overview(BaseModel):
    as_of: LocalDateTime
    empty_faces: int
    low_faces: int  # at or below min, but not empty
    short_picks_24h: int
    tasks_awaiting_approval: int
    tasks_approved: int  # approved, waiting for the crew
    open_discrepancies: int
    zones: list[ZoneHealth]
    short_picks_by_hour: list[HourBucket]  # oldest first, the last bucket is the current hour
    urgent_needs: list[ReplenishmentNeed]  # most urgent first, without an open task yet


def get_overview(session: Session, *, now: datetime) -> Overview:
    floor = get_floor_map(session)

    window_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=HOURS - 1)
    shorts = list_short_picks(session, now=now, since=window_start, limit=100_000)
    buckets = [window_start + timedelta(hours=i) for i in range(HOURS)]
    per_hour = dict.fromkeys(buckets, 0)
    per_zone = dict.fromkeys("ABC", 0)
    for short in shorts:
        per_hour[short.completed_at.replace(minute=0, second=0, microsecond=0)] += 1
        per_zone[short.zone] = per_zone.get(short.zone, 0) + 1

    zones = []
    for zone in sorted({bay.zone for bay in floor.bays}):
        statuses = [bay.pick.status for bay in floor.bays if bay.zone == zone]
        zones.append(
            ZoneHealth(
                zone=zone,
                ok=statuses.count("ok"),
                low=statuses.count("low"),
                empty=statuses.count("empty"),
                unassigned=statuses.count("unassigned"),
                short_picks=per_zone.get(zone, 0),
            )
        )

    task_counts = dict(
        session.exec(
            select(ReplenishmentTask.status, func.count()).group_by(col(ReplenishmentTask.status))
        ).all()
    )
    discrepancies = session.exec(
        select(func.count())
        .select_from(CycleCount)
        .where(col(CycleCount.status).in_(OPEN_COUNT_STATUSES))
    ).one()

    needs = [n for n in list_replenishment_needs(session) if n.open_task_id is None]

    return Overview(
        as_of=now,
        empty_faces=floor.counts["empty"],
        low_faces=floor.counts["low"],
        short_picks_24h=len(shorts),
        tasks_awaiting_approval=task_counts.get(ReplenishmentStatus.PROPOSED, 0),
        tasks_approved=task_counts.get(ReplenishmentStatus.APPROVED, 0),
        open_discrepancies=discrepancies,
        zones=zones,
        short_picks_by_hour=[HourBucket(hour_start=h, short_picks=per_hour[h]) for h in buckets],
        urgent_needs=needs[:URGENT_NEEDS],
    )
