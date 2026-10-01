"""Result types returned by the services (and, unchanged, by the MCP tools).

These are plain Pydantic models, not tables: the shape a caller needs, joined and
flattened, rather than the shape the data is stored in.
"""

from typing import Annotated

from pydantic import BaseModel, NaiveDatetime, WithJsonSchema

from warehouse_ops.db.models import ReplenishmentStatus, SkuCategory, Uom

# Warehouse local time, e.g. "2026-06-01T13:00:00". The schema is a plain string on
# purpose: JSON Schema's "date-time" format requires a UTC offset, so strict MCP
# clients reject naive times that are declared as "date-time".
LocalDateTime = Annotated[
    NaiveDatetime,
    WithJsonSchema(
        {"type": "string", "description": "Warehouse local time, ISO 8601 without offset"}
    ),
]


class ShortPick(BaseModel):
    task_id: int
    completed_at: LocalDateTime
    order_number: str
    location: str
    zone: str
    sku_code: str
    description: str
    expected_qty: int
    picked_qty: int
    short_qty: int
    picker: str


class SkuInfo(BaseModel):
    sku_code: str
    description: str
    category: SkuCategory
    uom: Uom
    case_qty: int


class PickFaceStock(BaseModel):
    location: str
    on_hand: int
    min_qty: int
    max_qty: int


class Pallet(BaseModel):
    location: str
    lpn: str
    qty: int
    received_at: LocalDateTime


class StockReport(BaseModel):
    sku: SkuInfo
    pick_face: PickFaceStock
    reserve_pallets: list[Pallet]  # oldest first (FIFO)
    reserve_qty: int
    total_qty: int


class ReplenishmentNeed(BaseModel):
    location: str
    zone: str
    sku_code: str
    description: str
    on_hand: int
    min_qty: int
    max_qty: int
    open_demand: int  # qty on OPEN pick tasks at this face
    reasons: list[str]
    suggested_qty: int  # whole cases, up to max and up to the source pallet's qty
    source: Pallet | None  # oldest reserve pallet; None means no reserve stock
    open_task_id: int | None  # an existing PROPOSED/APPROVED replenishment task


class ReplenishmentTaskOut(BaseModel):
    task_id: int
    status: ReplenishmentStatus
    sku_code: str
    description: str
    from_location: str
    to_location: str
    lpn: str | None
    qty: int
    reason: str
    created_by: str
    created_at: LocalDateTime
    approved_by: str | None  # who approved or rejected it
    decided_at: LocalDateTime | None
