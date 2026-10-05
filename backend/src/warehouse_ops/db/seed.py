"""Deterministic fake-data generator for the fishing tackle warehouse.

Run from backend/:  python -m uv run seed-db [--seed 42] [--as-of 2026-06-01T13:00]

The same ``seed`` and ``as_of`` always produce the same database, so tests and evals
can rely on it. ``as_of`` is "now" for the generated data: orders cover that day and the
two days before it.

What gets planted on purpose, so the tools always have something to find:
- a few pick faces below min, each with short picks in the 24 hours before ``as_of``
- some of those SKUs have no reserve stock at all (a true stockout)
- two open (APPROVED) replenishment tasks for below-min faces
- a few older orders that are still not shipped past their ship-by time (late orders)
- an inventory ledger explaining every quantity, plus six cycle count scenarios (db/history.py)
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from random import Random
from typing import Protocol

from faker import Faker
from sqlalchemy import Engine
from sqlmodel import Session

from warehouse_ops.db.catalog import CATEGORIES, ZONES, generate_catalog
from warehouse_ops.db.engine import get_engine, reset_db
from warehouse_ops.db.history import seed_history
from warehouse_ops.db.models import (
    Inventory,
    Location,
    LocationType,
    Order,
    OrderLine,
    OrderStatus,
    Picker,
    PickFace,
    PickTask,
    PickTaskStatus,
    ReplenishmentStatus,
    ReplenishmentTask,
    Shift,
    Sku,
    VelocityClass,
)

DEFAULT_SEED = 42

# Layout: every bay has one pick face (level 1) with two reserve slots above it.
AISLES_PER_ZONE = {"A": 4, "B": 3, "C": 3}
BAYS_PER_AISLE = 40
RESERVE_LEVELS = (2, 3)
STAGING_LANES = 6

VELOCITY_WEIGHTS = {"A": (30, 40, 30), "B": (15, 35, 50), "C": (10, 30, 60)}  # A/B/C share
FACE_MAX_CASES = {VelocityClass.A: 6, VelocityClass.B: 4, VelocityClass.C: 2}
ORDER_WEIGHT = {VelocityClass.A: 10, VelocityClass.B: 3, VelocityClass.C: 1}
RESERVE_PALLETS = {VelocityClass.A: (2, 3), VelocityClass.B: (1, 2), VelocityClass.C: (1, 2)}

PICKERS_PER_SHIFT = {Shift.FIRST: 9, Shift.SECOND: 6}
SECOND_SHIFT_START = time(14, 30)
ORDERS_PER_DAY = (180, 220)
WEB_ORDER_SHARE = 0.4
STUCK_ORDER_SHARE = {2: 0.03, 1: 0.06}  # days before as_of -> share left with an open pick

BELOW_MIN_SHARE = 0.04
STOCKOUT_COUNT = 3
NOISE_SHORT_RATE = 0.01  # random shorts (damaged/mis-slotted), unrelated to replenishment
DONE_REPLEN_TASKS = 15
OPEN_REPLEN_TASKS = 2


@dataclass(frozen=True)
class SeedSummary:
    skus: int
    locations: int
    pick_faces: int
    pallets: int
    orders: int
    order_lines: int
    pick_tasks: int
    short_picks: int
    below_min_faces: int
    stockouts: int
    late_orders: int
    replenishment_tasks: int
    ledger_rows: int
    planted_discrepancies: int  # shelf variance rows (a mis-slot plants two)


class _HasId(Protocol):
    id: int | None


def _id(row: _HasId) -> int:
    """Primary key of a flushed row (typed as ``int | None`` on the model)."""
    assert row.id is not None, f"{type(row).__name__} has not been flushed"
    return row.id


def seed_database(
    engine: Engine, *, seed: int = DEFAULT_SEED, as_of: datetime | None = None
) -> SeedSummary:
    """Drop all tables, recreate them and fill them with fake data."""
    as_of = (as_of or datetime.now()).replace(second=0, microsecond=0)
    rng = Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)

    reset_db(engine)
    with Session(engine) as session:
        skus = _create_skus(session, rng)
        locations = _create_locations(session)
        faces = _create_pick_faces(session, skus, locations)
        pickers = _create_pickers(session, fake)
        orders, lines, tasks = _create_orders(session, rng, fake, skus, faces, pickers, as_of)
        problem_sku_ids = _plant_short_picks(rng, tasks, faces, as_of)
        _set_order_statuses(orders, tasks, lines, as_of)
        session.add_all(tasks)

        stockout_ids = set(rng.sample(sorted(problem_sku_ids), STOCKOUT_COUNT))
        pallets = _create_inventory(
            session, rng, skus, locations, faces, problem_sku_ids, stockout_ids, as_of
        )
        replen = _create_replenishment_tasks(
            session, rng, fake, skus, faces, pallets, problem_sku_ids, stockout_ids, as_of
        )
        # Last, with its own random generators, so everything above is unchanged by it.
        history = seed_history(session, seed=seed, as_of=as_of)
        session.commit()

        return SeedSummary(
            skus=len(skus),
            locations=len(locations),
            pick_faces=len(faces),
            pallets=len(pallets),
            orders=len(orders),
            order_lines=len(lines),
            pick_tasks=len(tasks),
            short_picks=sum(t.status == PickTaskStatus.SHORT for t in tasks),
            below_min_faces=len(problem_sku_ids),
            stockouts=len(stockout_ids),
            late_orders=sum(o.status != OrderStatus.SHIPPED and o.ship_by < as_of for o in orders),
            replenishment_tasks=len(replen),
            ledger_rows=history.ledger_rows,
            planted_discrepancies=sum(len(v) for v in history.scenarios.values()),
        )


def _create_skus(session: Session, rng: Random) -> dict[int, Sku]:
    catalog = generate_catalog(rng)
    codes = rng.sample(range(10000, 100000), len(catalog))
    skus = []
    for item, code in zip(catalog, codes, strict=True):
        spec = CATEGORIES[item.category]
        velocity = rng.choices(list(VelocityClass), weights=VELOCITY_WEIGHTS[spec.zone])[0]
        skus.append(
            Sku(
                sku_code=str(code),
                description=item.description,
                brand=item.brand,
                category=item.category,
                uom=spec.uom,
                case_qty=rng.choice(spec.case_qtys),
                velocity_class=velocity,
            )
        )
    session.add_all(skus)
    session.flush()  # assigns ids
    return {_id(s): s for s in skus}


def _create_locations(session: Session) -> dict[int, Location]:
    locations = []
    global_aisle = 0
    for zone in ZONES:
        for aisle in range(1, AISLES_PER_ZONE[zone] + 1):
            global_aisle += 1
            for bay in range(1, BAYS_PER_AISLE + 1):
                for level in (1, *RESERVE_LEVELS):
                    locations.append(
                        Location(
                            code=f"{zone}-{aisle:02d}-{bay:02d}-{level}",
                            zone=zone,
                            aisle=aisle,
                            bay=bay,
                            level=level,
                            type=LocationType.PICK if level == 1 else LocationType.RESERVE,
                            x=global_aisle * 3,  # leave room for a walkway between aisles
                            y=bay,
                        )
                    )
    for lane in range(1, STAGING_LANES + 1):
        locations.append(
            Location(
                code=f"STG-{lane:02d}",
                zone="S",
                aisle=0,
                bay=lane,
                level=1,
                type=LocationType.STAGING,
                x=global_aisle * 3 + 4,
                y=lane * 6,
            )
        )
    session.add_all(locations)
    session.flush()
    return {_id(loc): loc for loc in locations}


def _create_pick_faces(
    session: Session, skus: dict[int, Sku], locations: dict[int, Location]
) -> dict[int, PickFace]:
    """Slot each SKU into a pick face in its zone, fast movers nearest the front (low bays)."""
    faces: dict[int, PickFace] = {}
    for zone in ZONES:
        zone_skus = sorted(
            (s for s in skus.values() if CATEGORIES[s.category].zone == zone),
            key=lambda s: (s.velocity_class, s.sku_code),
        )
        slots = sorted(
            (
                loc
                for loc in locations.values()
                if loc.zone == zone and loc.type == LocationType.PICK
            ),
            key=lambda loc: (loc.bay, loc.aisle),
        )
        for sku, slot in zip(zone_skus, slots, strict=False):
            max_qty = sku.case_qty * FACE_MAX_CASES[sku.velocity_class]
            faces[_id(sku)] = PickFace(
                location_id=_id(slot),
                sku_id=_id(sku),
                min_qty=max(1, max_qty // 4),
                max_qty=max_qty,
            )
    session.add_all(faces.values())
    session.flush()
    return faces


def _create_pickers(session: Session, fake: Faker) -> dict[Shift, list[Picker]]:
    pickers = {
        shift: [Picker(name=fake.name(), shift=shift) for _ in range(n)]
        for shift, n in PICKERS_PER_SHIFT.items()
    }
    session.add_all([p for group in pickers.values() for p in group])
    session.flush()
    return pickers


def _customer_pool(fake: Faker) -> list[str]:
    templates = (
        "{last}'s Bait & Tackle",
        "{city} Tackle Co.",
        "{city} Sporting Goods",
        "{last} Outdoors",
        "{city} Marina Supply",
    )
    return [
        template.format(last=fake.last_name(), city=fake.city())
        for template in templates
        for _ in range(8)
    ]


def _create_orders(
    session: Session,
    rng: Random,
    fake: Faker,
    skus: dict[int, Sku],
    faces: dict[int, PickFace],
    pickers: dict[Shift, list[Picker]],
    as_of: datetime,
) -> tuple[list[Order], list[OrderLine], list[PickTask]]:
    """Create orders, order lines and one pick task per line (statuses set later)."""
    shops = _customer_pool(fake)
    sku_ids = list(skus)
    weights = [ORDER_WEIGHT[skus[i].velocity_class] for i in sku_ids]

    orders: list[Order] = []
    order_skus: list[list[tuple[int, int]]] = []  # (sku_id, qty) per order
    stuck: set[int] = set()  # indexes of orders kept from finishing
    for days_back in (2, 1, 0):
        day: date = as_of.date() - timedelta(days=days_back)
        times = sorted(
            datetime.combine(day, time(6)) + timedelta(minutes=rng.randint(0, 16 * 60))
            for _ in range(rng.randint(*ORDERS_PER_DAY))
        )
        for created in times:
            is_web = rng.random() < WEB_ORDER_SHARE
            customer = f"Web: {fake.name()}" if is_web else rng.choice(shops)
            if created > as_of:
                break  # times are sorted, so the rest of the day is in the future too
            n_lines = rng.randint(1, 2) if is_web else rng.randint(1, 6)
            line_skus = list(dict.fromkeys(rng.choices(sku_ids, weights=weights, k=n_lines)))
            lines = []
            for sku_id in line_skus:
                max_qty = CATEGORIES[skus[sku_id].category].max_line_qty
                lines.append((sku_id, rng.randint(1, min(2, max_qty) if is_web else max_qty)))
            if rng.random() < STUCK_ORDER_SHARE.get(days_back, 0):
                stuck.add(len(orders))
            orders.append(
                Order(
                    order_number=f"SO-{100001 + len(orders)}",
                    customer=customer,
                    created_at=created,
                    ship_by=datetime.combine(created.date() + timedelta(days=1), time(15)),
                    status=OrderStatus.OPEN,
                )
            )
            order_skus.append(lines)
    session.add_all(orders)
    session.flush()

    order_lines = [
        OrderLine(order_id=_id(order), sku_id=sku_id, qty=qty)
        for order, lines in zip(orders, order_skus, strict=True)
        for sku_id, qty in lines
    ]
    session.add_all(order_lines)
    session.flush()

    orders_by_id = {_id(o): (i, o) for i, o in enumerate(orders)}
    tasks: list[PickTask] = []
    stuck_done: set[int] = set()
    for line in order_lines:
        index, order = orders_by_id[line.order_id]
        task = PickTask(
            order_line_id=_id(line),
            location_id=faces[line.sku_id].location_id,
            expected_qty=line.qty,
            status=PickTaskStatus.OPEN,
        )
        completed = order.created_at + timedelta(minutes=rng.randint(15, 300))
        is_noise_short = rng.random() < NOISE_SHORT_RATE
        picker_draw = rng.random()
        keep_open = index in stuck and index not in stuck_done
        if keep_open:
            stuck_done.add(index)  # one open pick is enough to hold the order back
        elif completed <= as_of:
            shift = (
                Shift.FIRST if time(6) <= completed.time() < SECOND_SHIFT_START else Shift.SECOND
            )
            crew = pickers[shift]
            task.picker_id = _id(crew[int(picker_draw * len(crew))])
            task.completed_at = completed
            task.picked_qty = line.qty
            task.status = PickTaskStatus.PICKED
            if is_noise_short and line.qty >= 2:
                task.picked_qty = line.qty - 1
                task.status = PickTaskStatus.SHORT
        tasks.append(task)
    return orders, order_lines, tasks


def _plant_short_picks(
    rng: Random, tasks: list[PickTask], faces: dict[int, PickFace], as_of: datetime
) -> set[int]:
    """Choose SKUs picked in the last 24h and turn their latest 1-3 picks into shorts.

    Returns the SKU ids whose pick faces will be stocked below min.
    """
    recent_by_location: dict[int, list[PickTask]] = defaultdict(list)
    for task in tasks:
        if task.completed_at is not None and task.completed_at >= as_of - timedelta(hours=24):
            recent_by_location[task.location_id].append(task)

    sku_by_location = {face.location_id: sku_id for sku_id, face in faces.items()}
    candidates = sorted(recent_by_location)
    n_problem = min(len(candidates), round(len(faces) * BELOW_MIN_SHARE))
    problem_skus: set[int] = set()
    for location_id in rng.sample(candidates, n_problem):
        recent = sorted(recent_by_location[location_id], key=lambda t: t.completed_at or as_of)
        for task in recent[-rng.randint(1, 3) :]:
            task.picked_qty = rng.randint(0, task.expected_qty - 1)
            task.status = PickTaskStatus.SHORT
        problem_skus.add(sku_by_location[location_id])
    return problem_skus


def _set_order_statuses(
    orders: list[Order], tasks: list[PickTask], lines: list[OrderLine], as_of: datetime
) -> None:
    order_by_line = {_id(line): line.order_id for line in lines}
    tasks_by_order: dict[int, list[PickTask]] = defaultdict(list)
    for task in tasks:
        tasks_by_order[order_by_line[task.order_line_id]].append(task)

    for order in orders:
        done = [t.completed_at for t in tasks_by_order[_id(order)] if t.completed_at is not None]
        if not done:
            order.status = OrderStatus.OPEN
        elif len(done) < len(tasks_by_order[_id(order)]):
            order.status = OrderStatus.IN_PROGRESS
        elif max(done) + timedelta(hours=2) <= as_of:
            order.status = OrderStatus.SHIPPED  # trucks leave a couple of hours after picking
        else:
            order.status = OrderStatus.PICKED


def _create_inventory(
    session: Session,
    rng: Random,
    skus: dict[int, Sku],
    locations: dict[int, Location],
    faces: dict[int, PickFace],
    problem_sku_ids: set[int],
    stockout_ids: set[int],
    as_of: datetime,
) -> list[Inventory]:
    """Stock every pick face, and put full pallets in the nearest free reserve slots.

    Returns the reserve pallets.
    """
    pick_stock = []
    for sku_id, face in faces.items():
        if sku_id in problem_sku_ids:
            qty = 0 if rng.random() < 0.5 else rng.randint(0, face.min_qty - 1)
        else:
            qty = rng.randint(face.min_qty + 1, face.max_qty)
        pick_stock.append(
            Inventory(
                location_id=face.location_id,
                sku_id=sku_id,
                qty=qty,
                received_at=as_of - timedelta(minutes=rng.randint(60, 72 * 60)),
            )
        )

    free_reserve = {loc_id for loc_id, loc in locations.items() if loc.type == LocationType.RESERVE}
    used_lpns: set[str] = set()
    pallets = []
    for sku_id, face in faces.items():
        if sku_id in stockout_ids:
            continue
        sku = skus[sku_id]
        home = locations[face.location_id]
        nearest = sorted(
            (loc_id for loc_id in free_reserve if locations[loc_id].zone == home.zone),
            key=lambda loc_id: (
                abs(locations[loc_id].x - home.x) + abs(locations[loc_id].y - home.y),
                locations[loc_id].code,
            ),
        )
        cases = CATEGORIES[sku.category].cases_per_pallet
        for loc_id in nearest[: rng.randint(*RESERVE_PALLETS[sku.velocity_class])]:
            free_reserve.remove(loc_id)
            lpn = f"LPN{rng.randint(10**7, 10**8 - 1)}"
            while lpn in used_lpns:
                lpn = f"LPN{rng.randint(10**7, 10**8 - 1)}"
            used_lpns.add(lpn)
            pallets.append(
                Inventory(
                    location_id=loc_id,
                    sku_id=sku_id,
                    lpn=lpn,
                    qty=sku.case_qty * rng.randint(*cases),
                    received_at=as_of
                    - timedelta(days=rng.randint(1, 60), minutes=rng.randint(0, 600)),
                )
            )

    session.add_all(pick_stock + pallets)
    session.flush()
    return pallets


def _create_replenishment_tasks(
    session: Session,
    rng: Random,
    fake: Faker,
    skus: dict[int, Sku],
    faces: dict[int, PickFace],
    pallets: list[Inventory],
    problem_sku_ids: set[int],
    stockout_ids: set[int],
    as_of: datetime,
) -> list[ReplenishmentTask]:
    """A history of finished replenishments, plus two approved ones still open."""
    supervisors = [fake.name() for _ in range(2)]
    pallets_by_sku: dict[int, list[Inventory]] = defaultdict(list)
    for pallet in pallets:
        pallets_by_sku[pallet.sku_id].append(pallet)

    def task_for(sku_id: int, created: datetime, qty: int) -> ReplenishmentTask:
        source = min(pallets_by_sku[sku_id], key=lambda p: p.received_at)  # FIFO
        return ReplenishmentTask(
            sku_id=sku_id,
            from_location_id=source.location_id,
            to_location_id=faces[sku_id].location_id,
            lpn=source.lpn,
            qty=min(qty, source.qty),
            reason="Pick face at or below min",
            status=ReplenishmentStatus.DONE,
            created_by=rng.choice(supervisors),
            approved_by=rng.choice(supervisors),
            created_at=created,
            decided_at=created + timedelta(minutes=rng.randint(2, 20)),
        )

    healthy = sorted(set(pallets_by_sku) - problem_sku_ids)
    tasks = [
        task_for(
            sku_id,
            as_of - timedelta(minutes=rng.randint(6 * 60, 48 * 60)),
            skus[sku_id].case_qty * rng.randint(1, 3),
        )
        for sku_id in rng.sample(healthy, DONE_REPLEN_TASKS)
    ]

    for sku_id in rng.sample(sorted(problem_sku_ids - stockout_ids), OPEN_REPLEN_TASKS):
        face = faces[sku_id]
        # on-hand is below min, so max - min always fits under max
        qty = face.max_qty - face.min_qty
        task = task_for(sku_id, as_of - timedelta(minutes=rng.randint(10, 45)), qty)
        task.status = ReplenishmentStatus.APPROVED
        tasks.append(task)

    session.add_all(tasks)
    session.flush()
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the database and fill it with fake data.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--as-of",
        type=datetime.fromisoformat,
        default=None,
        help="'now' for the generated data, e.g. 2026-06-01T13:00 (default: current time)",
    )
    parser.add_argument(
        "--db-url", default=None, help="defaults to $DATABASE_URL or backend/warehouse.db"
    )
    args = parser.parse_args()

    summary = seed_database(get_engine(args.db_url), seed=args.seed, as_of=args.as_of)
    for field, value in vars(summary).items():
        print(f"{field:>20}: {value}")
