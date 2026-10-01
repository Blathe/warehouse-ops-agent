"""Fishing product catalog used by the seed generator.

Every candidate description is built from word lists, then the generator samples
from them. Brands are fictional.
"""

from dataclasses import dataclass
from itertools import product
from random import Random

from warehouse_ops.db.models import SkuCategory, Uom

BRANDS = [
    "Ridgeline",
    "Bluegill Bay",
    "Ironwake",
    "Northfork",
    "Stillwater",
    "Kettle River",
    "Driftline",
    "Hollow Pine",
]


@dataclass(frozen=True)
class CategorySpec:
    zone: str
    count: int  # how many SKUs to generate
    uom: Uom
    case_qtys: tuple[int, ...]
    cases_per_pallet: tuple[int, int]  # inclusive range
    max_line_qty: int  # largest qty a customer orders on one line


CATEGORIES: dict[SkuCategory, CategorySpec] = {
    # Zone A: small tackle
    SkuCategory.LURE: CategorySpec("A", 50, Uom.EA, (12, 24), (20, 40), 12),
    SkuCategory.SOFT_PLASTIC: CategorySpec("A", 35, Uom.PK, (12, 24, 48), (20, 40), 12),
    SkuCategory.TERMINAL_TACKLE: CategorySpec("A", 30, Uom.PK, (24, 48), (20, 40), 12),
    SkuCategory.LINE: CategorySpec("A", 25, Uom.SPOOL, (6, 12), (20, 40), 6),
    # Zone B: rods & reels
    SkuCategory.ROD: CategorySpec("B", 35, Uom.EA, (4, 6), (8, 16), 4),
    SkuCategory.REEL: CategorySpec("B", 30, Uom.EA, (2, 4, 6), (8, 16), 4),
    SkuCategory.COMBO: CategorySpec("B", 15, Uom.EA, (2, 4), (8, 16), 3),
    # Zone C: bulky gear
    SkuCategory.TACKLE_STORAGE: CategorySpec("C", 15, Uom.EA, (2, 4, 6), (4, 10), 3),
    SkuCategory.NET: CategorySpec("C", 12, Uom.EA, (2, 4), (4, 10), 2),
    SkuCategory.COOLER: CategorySpec("C", 15, Uom.EA, (1, 2), (4, 10), 2),
    SkuCategory.APPAREL: CategorySpec("C", 23, Uom.EA, (4, 6), (4, 10), 2),
    SkuCategory.ELECTRONICS: CategorySpec("C", 15, Uom.EA, (1, 2), (4, 10), 1),
}

ZONES = ("A", "B", "C")

_LURE_TYPES = {
    "Crankbait": ("1/4oz", "3/8oz", "1/2oz"),
    "Jerkbait": ("3.5in", "4.5in", "5in"),
    "Spinnerbait": ("1/4oz", "3/8oz", "1/2oz"),
    "Topwater Popper": ("2.5in", "3in", "3.5in"),
    "Inline Spinner": ("#2", "#3", "#4"),
    "Casting Spoon": ("1/4oz", "1/2oz", "3/4oz"),
    "Football Jig": ("3/8oz", "1/2oz", "3/4oz"),
}
_LURE_COLORS = (
    "Firetiger",
    "Chartreuse Shad",
    "Perch",
    "Black/Blue",
    "Silver Flash",
    "Craw",
    "Bluegill",
    "White",
)
_PLASTIC_TYPES = {
    "Stick Worm": ("5in", "6in", "7in"),
    "Paddle Tail Swimbait": ("3in", "4in", "5in"),
    "Creature Bait": ("3.5in", "4in", "5in"),
    "Tube Bait": ("2.5in", "3.5in", "4in"),
    "Ned Worm": ("2.75in", "3in", "3.5in"),
}
_PLASTIC_COLORS = ("Green Pumpkin", "Watermelon Red", "Junebug", "Smoke Pepper", "Pearl", "Black")


def _candidates(category: SkuCategory) -> list[str]:
    match category:
        case SkuCategory.LURE:
            return [
                f"{t} {size} {color}"
                for t, sizes in _LURE_TYPES.items()
                for size, color in product(sizes, _LURE_COLORS)
            ]
        case SkuCategory.SOFT_PLASTIC:
            return [
                f"{t} {size} {color} 8pk"
                for t, sizes in _PLASTIC_TYPES.items()
                for size, color in product(sizes, _PLASTIC_COLORS)
            ]
        case SkuCategory.TERMINAL_TACKLE:
            hooks = [
                f"{h} Hook {s} 25pk"
                for h, s in product(
                    ("Offset Worm", "Octopus", "Treble", "Circle"),
                    ("#6", "#4", "#2", "1/0", "2/0", "3/0"),
                )
            ]
            sinkers = [
                f"{w} {s} 10pk"
                for w, s in product(
                    ("Bullet Weight", "Split Shot", "Egg Sinker", "Bank Sinker"),
                    ("1/8oz", "1/4oz", "3/8oz", "1/2oz"),
                )
            ]
            swivels = [
                f"{w} {s} 10pk"
                for w, s in product(
                    ("Barrel Swivel", "Snap Swivel", "Ball Bearing Swivel"), ("#10", "#7", "#5")
                )
            ]
            return hooks + sinkers + swivels
        case SkuCategory.LINE:
            return [
                f"{lb}lb {kind} Line {yd}yd"
                for kind, lb, yd in product(
                    ("Monofilament", "Fluorocarbon", "Braided"),
                    (6, 8, 10, 12, 15, 20, 30, 50),
                    (150, 300),
                )
            ]
        case SkuCategory.ROD:
            powers = ("Medium Light", "Medium", "Medium Heavy", "Heavy")
            return (
                [
                    f"{length} {power} {kind} Rod"
                    for kind, length, power in product(
                        ("Spinning", "Casting"), ("6ft 6in", "7ft", "7ft 3in"), powers
                    )
                ]
                + [f"9ft {wt}wt Fly Rod" for wt in (4, 5, 6, 8)]
                + [
                    f"{length} {power} Surf Spinning Rod"
                    for length, power in product(
                        ("9ft", "10ft", "11ft"), ("Medium", "Medium Heavy")
                    )
                ]
                + [
                    f"{length} {power} Ice Rod"
                    for length, power in product(("24in", "28in", "32in"), ("Light", "Medium"))
                ]
            )
        case SkuCategory.REEL:
            return (
                [
                    f"{size} {tier}Spinning Reel"
                    for size, tier in product((1000, 2000, 2500, 3000, 4000, 5000), ("", "Pro "))
                ]
                + [
                    f"{tier}Baitcasting Reel {ratio} {hand}"
                    for tier, ratio, hand in product(
                        ("", "Pro "), ("6.4:1", "7.1:1", "8.1:1"), ("RH", "LH")
                    )
                ]
                + [
                    f"{tier}Fly Reel {wt}"
                    for tier, wt in product(("", "Pro "), ("3/4wt", "5/6wt", "7/8wt"))
                ]
                + ["Spincast Reel 10lb", "Spincast Reel 20lb"]
            )
        case SkuCategory.COMBO:
            return [
                f"{length} {power} {kind} Combo"
                for kind, length, power in product(
                    ("Spinning", "Casting"),
                    ("6ft 6in", "7ft", "7ft 3in"),
                    ("Medium Light", "Medium", "Medium Heavy", "Heavy"),
                )
            ] + ["5ft Youth Spincast Combo"]
        case SkuCategory.TACKLE_STORAGE:
            return (
                [
                    f"{size} Tackle Tray {depth}"
                    for size, depth in product((3600, 3700), ("Shallow", "Deep"))
                ]
                + [f"{n}-Tray Tackle Box" for n in (2, 3, 4)]
                + [f"Soft Tackle Bag {s}" for s in ("Small", "Medium", "Large")]
                + [
                    "Tackle Backpack",
                    "Rod Case 7ft",
                    "Rod Case 9ft",
                    "Bait Bucket 8qt",
                    "Wading Belt Pouch",
                ]
            )
        case SkuCategory.NET:
            return [
                f"{kind} Landing Net {size}"
                for kind, size in product(
                    ("Rubber Mesh", "Knotless", "Telescoping"), ("Small", "Medium", "Large")
                )
            ] + [f"Cast Net {ft}ft" for ft in (4, 6, 8)]
        case SkuCategory.COOLER:
            return (
                [f"{qt}qt Hard Cooler" for qt in (20, 35, 45, 65, 75, 110)]
                + [f"{cans}-Can Soft Cooler" for cans in (12, 24, 30)]
                + [f"{qt}qt Wheeled Cooler" for qt in (50, 60, 100)]
                + ["6qt Bait Cooler", "12qt Bait Cooler", "19qt Aerated Bait Cooler"]
            )
        case SkuCategory.APPAREL:
            return (
                [f"Breathable Chest Waders {s}" for s in ("S", "M", "L", "XL", "XXL")]
                + [f"Neoprene Waders {s}" for s in ("S", "M", "L", "XL")]
                + [f"Wading Boots Size {s}" for s in (9, 10, 11, 12, 13)]
                + [f"Rain Jacket {s}" for s in ("M", "L", "XL")]
                + [f"Sun Hoodie {s}" for s in ("S", "M", "L", "XL")]
                + ["Fishing Gloves M/L", "Fishing Gloves L/XL"]
            )
        case SkuCategory.ELECTRONICS:
            return (
                [
                    f"{size} Fish Finder {kind}"
                    for size, kind in product(("5in", "7in", "9in", "12in"), ("Sonar", "GPS Combo"))
                ]
                + ["Standard Transducer", "Side Imaging Transducer"]
                + [f"Trolling Motor {lb}lb Thrust" for lb in (30, 55, 80)]
                + ["Marine Battery 12V 100Ah", "Digital Fish Scale"]
            )


@dataclass(frozen=True)
class CatalogItem:
    description: str
    brand: str
    category: SkuCategory


def generate_catalog(rng: Random) -> list[CatalogItem]:
    """Sample ``CategorySpec.count`` products per category, each with a random brand."""
    items: list[CatalogItem] = []
    for category, spec in CATEGORIES.items():
        candidates = _candidates(category)
        if len(candidates) < spec.count:
            raise ValueError(f"{category}: only {len(candidates)} candidates for {spec.count} SKUs")
        for description in rng.sample(candidates, spec.count):
            brand = rng.choice(BRANDS)
            items.append(CatalogItem(f"{brand} {description}", brand, category))
    return items
