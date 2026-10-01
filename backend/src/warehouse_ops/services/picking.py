from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from warehouse_ops.db.models import (
    Location,
    Order,
    OrderLine,
    Picker,
    PickTask,
    PickTaskStatus,
    Sku,
)
from warehouse_ops.services.schemas import ShortPick

DEFAULT_LOOKBACK = timedelta(hours=24)
MAX_RESULTS = 100


def list_short_picks(
    session: Session,
    *,
    now: datetime,
    since: datetime | None = None,
    zone: str | None = None,
    sku_code: str | None = None,
    limit: int = MAX_RESULTS,
) -> list[ShortPick]:
    """Short picks (picked less than expected) between ``since`` and ``now``, newest first.

    ``since`` defaults to 24 hours before ``now``.
    """
    # sqlmodel's select() is typed for up to 4 entities, so pickers are looked up separately.
    pickers = {p.id: p.name for p in session.exec(select(Picker))}
    statement = (
        select(PickTask, Order, Location, Sku)
        .join(OrderLine, col(OrderLine.id) == col(PickTask.order_line_id))
        .join(Order, col(Order.id) == col(OrderLine.order_id))
        .join(Location, col(Location.id) == col(PickTask.location_id))
        .join(Sku, col(Sku.id) == col(OrderLine.sku_id))
        .where(
            PickTask.status == PickTaskStatus.SHORT,
            col(PickTask.completed_at) >= (since or now - DEFAULT_LOOKBACK),
            col(PickTask.completed_at) <= now,
        )
        .order_by(col(PickTask.completed_at).desc(), col(PickTask.id).desc())
        .limit(limit)
    )
    if zone:
        statement = statement.where(Location.zone == zone.upper())
    if sku_code:
        statement = statement.where(Sku.sku_code == sku_code)

    results = []
    for task, order, location, sku in session.exec(statement):
        # Both are set on every completed task; the asserts narrow the types for mypy.
        assert task.id is not None and task.completed_at is not None
        assert task.picked_qty is not None
        results.append(
            ShortPick(
                task_id=task.id,
                completed_at=task.completed_at,
                order_number=order.order_number,
                location=location.code,
                zone=location.zone,
                sku_code=sku.sku_code,
                description=sku.description,
                expected_qty=task.expected_qty,
                picked_qty=task.picked_qty,
                short_qty=task.expected_qty - task.picked_qty,
                picker=pickers[task.picker_id],
            )
        )
    return results
