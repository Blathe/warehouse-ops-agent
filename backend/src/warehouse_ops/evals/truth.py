"""Ground truth for the eval cases, computed from the seeded database.

Cases refer to these facts by name (``{need_sku}``) instead of hard-coding codes, so the
expected answers always match whatever the seeder produced.
"""

from datetime import datetime

from sqlmodel import Session, select

from warehouse_ops.db.models import Sku
from warehouse_ops.evals.cases import Facts
from warehouse_ops.services import picking, replenishment


def build_facts(session: Session, now: datetime) -> Facts:
    short_a = picking.list_short_picks(session, now=now, zone="A")
    if not short_a:
        raise LookupError("The seed has no short picks in zone A in the last 24 hours")
    short_skus = {s.sku_code for s in picking.list_short_picks(session, now=now)}

    needs = replenishment.list_replenishment_needs(session)
    fixable = next(
        (n for n in needs if n.source and n.open_task_id is None and n.suggested_qty > 0), None
    )
    stockout = next((n for n in needs if n.source is None), None)
    open_task = next((n for n in needs if n.open_task_id is not None), None)
    top_a = next((n for n in needs if n.zone == "A"), None)
    if fixable is None or stockout is None or open_task is None or top_a is None:
        raise LookupError("The seed is missing a replenishment scenario the eval cases need")
    assert fixable.source is not None and open_task.open_task_id is not None

    all_codes = {sku.sku_code for sku in session.exec(select(Sku))}
    unknown_code = next(str(c) for c in range(10000, 100000) if str(c) not in all_codes)
    clean_code = next(code for code in sorted(all_codes) if code not in short_skus)

    return {
        "short_a_sku": short_a[0].sku_code,
        "short_a_location": short_a[0].location,
        "need_sku": fixable.sku_code,
        "need_face": fixable.location,
        "need_source": fixable.source.location,
        "need_qty": fixable.suggested_qty,
        "top_need_a_location": top_a.location,
        "stockout_sku": stockout.sku_code,
        "open_task_sku": open_task.sku_code,
        "open_task_id": open_task.open_task_id,
        "unknown_sku": unknown_code,
        "clean_sku": clean_code,
    }
