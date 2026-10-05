"""Seeded inventory history (the ledger) and the planted cycle count scenarios.

Runs after the rest of the seed, with its own random generators, so adding it didn't
change any of the data generated before it.

The ledger explains every current quantity: for each location and SKU, the rows sum to
the ``inventory`` qty. On top of ordinary history, six scenarios are planted, each with a
known cause that the cycle count investigator should find (see docs/spec.md):

- ``blank_adjustment``: a +N manual adjustment with a blank reason; the shelf is N short
- ``mis_slot``: a pallet put away one slot over; its slot is empty and the neighbour holds it
- ``case_vs_each``: a pallet counted in cases instead of units (a counting error)
- ``short_replen``: a finished replenishment moved N fewer units than it recorded
- ``mid_pick_count``: a face counted while a pick was in progress (not a real loss)
- ``unexplained_shrink``: a few units missing with nothing in the data to explain it
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from random import Random

from faker import Faker
from sqlmodel import Session, col, select

from warehouse_ops.db.models import (
    Inventory,
    InventoryTxn,
    Location,
    OrderLine,
    Picker,
    PickFace,
    PickTask,
    PickTaskStatus,
    ReplenishmentStatus,
    ReplenishmentTask,
    ShelfVariance,
    Sku,
    TxnType,
)

SCENARIOS = (
    "blank_adjustment",
    "mis_slot",
    "case_vs_each",
    "short_replen",
    "mid_pick_count",
    "unexplained_shrink",
)
TRANSIENT_SCENARIOS = {"case_vs_each", "mid_pick_count"}  # a recount wouldn't repeat these

BACKGROUND_ADJUSTMENTS = 8
ADJUSTMENT_REASONS = (
    ("Damaged in handling", -1),
    ("Damaged packaging, sent to returns", -2),
    ("Found during putaway", 1),
    ("Customer return restocked", 2),
    ("Water damage from roof leak", -3),
)


@dataclass
class HistorySummary:
    ledger_rows: int
    scenarios: dict[str, list[str]] = field(default_factory=dict)  # scenario -> location codes


@dataclass
class _Stock:
    """In-memory view of the seeded data the history is built from."""

    locations: dict[int, Location]
    skus: dict[int, Sku]
    faces: dict[int, PickFace]  # by location id
    inventory: list[Inventory]
    picks: list[PickTask]
    pick_skus: dict[int, int]  # pick task id -> sku id
    pickers: dict[int, str]
    replens: list[ReplenishmentTask]


def seed_history(session: Session, *, seed: int, as_of: datetime) -> HistorySummary:
    rng = Random(seed + 1_000_003)
    fake = Faker("en_US")
    fake.seed_instance(seed + 1)
    clerks = [fake.name() for _ in range(3)]
    drivers = [fake.name() for _ in range(2)]
    window_start = datetime.combine(as_of.date() - timedelta(days=2), time(0))

    stock = _load(session)
    txns: list[InventoryTxn] = []
    variances: list[ShelfVariance] = []
    planted = _plant_scenarios(rng, stock, clerks, as_of, window_start, txns, variances)

    _add_picks(stock, txns)
    _add_replenishments(rng, stock, drivers, as_of, txns)
    _add_background_adjustments(rng, stock, clerks, as_of, window_start, planted, txns)
    _add_opening_balances(rng, stock, clerks, as_of, window_start, txns)

    session.add_all(txns)
    session.add_all(variances)
    session.flush()

    scenarios: dict[str, list[str]] = defaultdict(list)
    for variance in variances:
        scenarios[variance.scenario].append(stock.locations[variance.location_id].code)
    return HistorySummary(ledger_rows=len(txns), scenarios=dict(scenarios))


def _load(session: Session) -> _Stock:
    return _Stock(
        locations={loc.id: loc for loc in session.exec(select(Location)) if loc.id is not None},
        skus={s.id: s for s in session.exec(select(Sku)) if s.id is not None},
        faces={f.location_id: f for f in session.exec(select(PickFace))},
        inventory=list(session.exec(select(Inventory).order_by(col(Inventory.id)))),
        picks=list(session.exec(select(PickTask).order_by(col(PickTask.id)))),
        pick_skus={
            task_id: sku_id
            for task_id, sku_id in session.exec(
                select(PickTask.id, OrderLine.sku_id).join(
                    OrderLine, col(OrderLine.id) == col(PickTask.order_line_id)
                )
            )
            if task_id is not None
        },
        pickers={p.id: p.name for p in session.exec(select(Picker)) if p.id is not None},
        replens=list(session.exec(select(ReplenishmentTask).order_by(col(ReplenishmentTask.id)))),
    )


def _plant_scenarios(
    rng: Random,
    stock: _Stock,
    clerks: list[str],
    as_of: datetime,
    window_start: datetime,
    txns: list[InventoryTxn],
    variances: list[ShelfVariance],
) -> set[int]:
    """Pick a distinct bay for each scenario and record its hidden truth.

    Returns the location ids involved, so background noise stays away from them.
    """
    locs = stock.locations
    used_bays: set[tuple[str, int, int]] = set()
    involved: set[int] = set()

    def bay(loc_id: int) -> tuple[str, int, int]:
        loc = locs[loc_id]
        return (loc.zone, loc.aisle, loc.bay)

    def free(*loc_ids: int) -> bool:
        return all(bay(i) not in used_bays for i in loc_ids)

    def claim(*loc_ids: int) -> None:
        for loc_id in loc_ids:
            used_bays.add(bay(loc_id))
            involved.add(loc_id)

    def vary(inv: Inventory, delta: int, scenario: str, loc_id: int | None = None) -> None:
        variances.append(
            ShelfVariance(
                location_id=loc_id if loc_id is not None else inv.location_id,
                sku_id=inv.sku_id,
                lpn=inv.lpn,
                delta=delta,
                scenario=scenario,
                transient=scenario in TRANSIENT_SCENARIOS,
            )
        )

    # Bays touched by open replenishment tasks keep their own story.
    open_replen = {
        loc_id
        for t in stock.replens
        if t.status in (ReplenishmentStatus.APPROVED, ReplenishmentStatus.PROPOSED)
        for loc_id in (t.from_location_id, t.to_location_id)
    }
    for loc_id in open_replen:
        used_bays.add(bay(loc_id))

    # Faces with an unconfirmed pick are kept for mid_pick_count, so no other scenario gets a
    # pick in progress as a red herring.
    open_pick_locations = {t.location_id for t in stock.picks if t.status == PickTaskStatus.OPEN}
    face_stock = [i for i in stock.inventory if i.location_id in stock.faces]
    pallets = [i for i in stock.inventory if i.lpn]
    healthy = [i for i in face_stock if i.qty > stock.faces[i.location_id].min_qty]

    # short_replen: a finished replenishment whose crew moved N fewer than recorded.
    done = [t for t in stock.replens if t.status == ReplenishmentStatus.DONE]
    for task in rng.sample(done, len(done)):
        source = next((p for p in pallets if p.lpn == task.lpn), None)
        face = next((i for i in face_stock if i.location_id == task.to_location_id), None)
        case_qty = stock.skus[task.sku_id].case_qty
        if source is None or face is None or task.qty < 2 * case_qty:
            continue
        if face.location_id in open_pick_locations:
            continue
        if face.qty < case_qty or not free(source.location_id, face.location_id):
            continue
        short_by = case_qty * (task.qty // case_qty // 2)
        claim(source.location_id, face.location_id)
        vary(face, -short_by, "short_replen")
        vary(source, short_by, "short_replen")
        break

    # mid_pick_count: a face with an open pick, counted after the units left the shelf.
    for inv in rng.sample(healthy, len(healthy)):
        pick = next(
            (
                t
                for t in stock.picks
                if t.location_id == inv.location_id and t.status == PickTaskStatus.OPEN
            ),
            None,
        )
        if pick is None or not 3 <= pick.expected_qty <= inv.qty or not free(inv.location_id):
            continue
        claim(inv.location_id)
        vary(inv, -pick.expected_qty, "mid_pick_count")
        break

    # Remaining face scenarios avoid faces with open picks, so only one story fits each.
    quiet = [i for i in healthy if i.location_id not in open_pick_locations and i.qty >= 12]
    quiet = rng.sample(quiet, len(quiet))

    # blank_adjustment: someone added stock with no reason; the shelf never had it.
    for inv in quiet:
        if not free(inv.location_id):
            continue
        amount = min(inv.qty, rng.randint(12, 30))
        claim(inv.location_id)
        txns.append(
            InventoryTxn(
                ts=window_start + timedelta(hours=rng.randint(14, 20), minutes=rng.randint(0, 59)),
                location_id=inv.location_id,
                sku_id=inv.sku_id,
                qty_change=amount,
                type=TxnType.ADJUSTMENT,
                user=clerks[1],
                reason="",
            )
        )
        vary(inv, -amount, "blank_adjustment")
        break

    # unexplained_shrink: a few units gone, nothing recorded.
    for inv in quiet:
        if not free(inv.location_id):
            continue
        claim(inv.location_id)
        vary(inv, -rng.randint(2, 6), "unexplained_shrink")
        break

    # mis_slot: a pallet sitting one slot over (same aisle and level), in an empty slot.
    occupied = {i.location_id for i in pallets}
    by_position = {
        (loc.zone, loc.aisle, loc.bay, loc.level): loc_id for loc_id, loc in locs.items()
    }
    for pallet in rng.sample(pallets, len(pallets)):
        here = locs[pallet.location_id]
        neighbours = [
            by_position.get((here.zone, here.aisle, here.bay + step, here.level))
            for step in (1, -1)
        ]
        target = next((n for n in neighbours if n is not None and n not in occupied), None)
        if target is None or not free(pallet.location_id, target):
            continue
        claim(pallet.location_id, target)
        vary(pallet, -pallet.qty, "mis_slot")
        vary(pallet, pallet.qty, "mis_slot", loc_id=target)
        break

    # case_vs_each: a clerk counts cases on a pallet instead of units.
    for pallet in rng.sample(pallets, len(pallets)):
        case_qty = stock.skus[pallet.sku_id].case_qty
        if case_qty < 6 or not free(pallet.location_id):
            continue
        claim(pallet.location_id)
        vary(pallet, pallet.qty // case_qty - pallet.qty, "case_vs_each")
        break

    found = {v.scenario for v in variances}
    missing = set(SCENARIOS) - found
    assert not missing, f"Could not plant {missing}; the seed data has changed shape"
    return involved


def _add_picks(stock: _Stock, txns: list[InventoryTxn]) -> None:
    for task in stock.picks:
        if task.completed_at is None or not task.picked_qty or task.id is None:
            continue
        txns.append(
            InventoryTxn(
                ts=task.completed_at,
                location_id=task.location_id,
                sku_id=stock.pick_skus[task.id],
                qty_change=-task.picked_qty,
                type=TxnType.PICK,
                user=stock.pickers.get(task.picker_id or -1, "unknown"),
                ref=f"pick_task:{task.id}",
            )
        )


def _add_replenishments(
    rng: Random, stock: _Stock, drivers: list[str], as_of: datetime, txns: list[InventoryTxn]
) -> None:
    for task in stock.replens:
        if task.status != ReplenishmentStatus.DONE or task.decided_at is None:
            continue
        moved_at = min(task.decided_at + timedelta(minutes=rng.randint(20, 90)), as_of)
        driver = rng.choice(drivers)
        ref = f"replenishment_task:{task.id}"
        txns += [
            InventoryTxn(
                ts=moved_at,
                location_id=task.from_location_id,
                sku_id=task.sku_id,
                lpn=task.lpn,
                qty_change=-task.qty,
                type=TxnType.REPLEN_OUT,
                user=driver,
                ref=ref,
            ),
            InventoryTxn(
                ts=moved_at,
                location_id=task.to_location_id,
                sku_id=task.sku_id,
                qty_change=task.qty,
                type=TxnType.REPLEN_IN,
                user=driver,
                ref=ref,
            ),
        ]


def _add_background_adjustments(
    rng: Random,
    stock: _Stock,
    clerks: list[str],
    as_of: datetime,
    window_start: datetime,
    planted: set[int],
    txns: list[InventoryTxn],
) -> None:
    """Ordinary adjustments with real reasons, so the planted blank one isn't the only one."""
    candidates = [
        i for i in stock.inventory if i.location_id in stock.faces and i.location_id not in planted
    ]
    span = int((as_of - window_start).total_seconds() // 60)
    for inv in rng.sample(candidates, BACKGROUND_ADJUSTMENTS):
        reason, change = rng.choice(ADJUSTMENT_REASONS)
        txns.append(
            InventoryTxn(
                ts=window_start + timedelta(minutes=rng.randint(6 * 60, span - 1)),
                location_id=inv.location_id,
                sku_id=inv.sku_id,
                qty_change=change,
                type=TxnType.ADJUSTMENT,
                user=rng.choice(clerks),
                reason=reason,
            )
        )


def _add_opening_balances(
    rng: Random,
    stock: _Stock,
    clerks: list[str],
    as_of: datetime,
    window_start: datetime,
    txns: list[InventoryTxn],
) -> None:
    """Start each stock record's history so its ledger sums to the current qty."""
    changes: dict[tuple[int, int], int] = defaultdict(int)
    for txn in txns:
        changes[(txn.location_id, txn.sku_id)] += txn.qty_change

    for inv in stock.inventory:
        opening = inv.qty - changes[(inv.location_id, inv.sku_id)]
        if inv.lpn and inv.received_at >= window_start:
            # Received during the window: the pallet's history starts with its receipt.
            txns.append(
                InventoryTxn(
                    ts=inv.received_at,
                    location_id=inv.location_id,
                    sku_id=inv.sku_id,
                    lpn=inv.lpn,
                    qty_change=opening,
                    type=TxnType.RECEIVE,
                    user=rng.choice(clerks),
                    ref=f"lpn:{inv.lpn}",
                )
            )
            continue
        if opening < 0:
            # More came in than the current qty explains: the difference left through picks
            # for orders outside the seeded order window (will-call and prior-day orders).
            pickers = sorted(stock.pickers.values())
            remaining = -opening
            while remaining > 0:
                qty = remaining if remaining <= 2 else rng.randint(1, remaining - 1)
                remaining -= qty
                txns.append(
                    InventoryTxn(
                        ts=as_of - timedelta(minutes=rng.randint(30, 600)),
                        location_id=inv.location_id,
                        sku_id=inv.sku_id,
                        qty_change=-qty,
                        type=TxnType.PICK,
                        user=rng.choice(pickers),
                        reason="Will-call order",
                    )
                )
            opening = 0
        if opening:
            txns.append(
                InventoryTxn(
                    ts=window_start,
                    location_id=inv.location_id,
                    sku_id=inv.sku_id,
                    lpn=inv.lpn,
                    qty_change=opening,
                    type=TxnType.OPENING,
                    user="system",
                )
            )
