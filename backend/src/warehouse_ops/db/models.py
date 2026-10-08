"""Database tables (see docs/spec.md, "Data model").

Each class with ``table=True`` is both a Pydantic model and a SQLAlchemy table,
roughly an EF Core entity that also works as a DTO.

Datetimes are naive (``NaiveDatetime``) and in warehouse local time, like a MySQL DATETIME.
"""

from enum import StrEnum

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


class SkuCategory(StrEnum):
    LURE = "LURE"
    SOFT_PLASTIC = "SOFT_PLASTIC"
    TERMINAL_TACKLE = "TERMINAL_TACKLE"
    LINE = "LINE"
    ROD = "ROD"
    REEL = "REEL"
    COMBO = "COMBO"
    TACKLE_STORAGE = "TACKLE_STORAGE"
    NET = "NET"
    COOLER = "COOLER"
    APPAREL = "APPAREL"
    ELECTRONICS = "ELECTRONICS"


class Uom(StrEnum):
    EA = "EA"
    PK = "PK"
    SPOOL = "SPOOL"


class VelocityClass(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class LocationType(StrEnum):
    PICK = "PICK"
    RESERVE = "RESERVE"
    STAGING = "STAGING"


class Shift(StrEnum):
    FIRST = "FIRST"
    SECOND = "SECOND"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"


class PickTaskStatus(StrEnum):
    OPEN = "OPEN"
    PICKED = "PICKED"
    SHORT = "SHORT"


class ReplenishmentStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DONE = "DONE"


class TxnType(StrEnum):
    OPENING = "OPENING"  # balance at the start of the recorded history
    RECEIVE = "RECEIVE"
    PICK = "PICK"
    REPLEN_OUT = "REPLEN_OUT"
    REPLEN_IN = "REPLEN_IN"
    ADJUSTMENT = "ADJUSTMENT"  # manual, by a person
    COUNT_ADJUSTMENT = "COUNT_ADJUSTMENT"  # accepting a cycle count


class CountStatus(StrEnum):
    MATCHED = "MATCHED"  # counted qty equals the system qty
    DISCREPANCY = "DISCREPANCY"  # open: waiting for a supervisor
    RECOUNT_REQUESTED = "RECOUNT_REQUESTED"  # the next count includes the location again
    RECOUNTED = "RECOUNTED"  # superseded by a newer count of the same location
    ACCEPTED = "ACCEPTED"  # the system was adjusted to the count


class InvestigationStatus(StrEnum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class Approval(StrEnum):
    NOT_APPLICABLE = "n/a"
    APPROVED = "approved"
    REJECTED = "rejected"


class Sku(SQLModel, table=True):
    __tablename__ = "sku"

    id: int | None = Field(default=None, primary_key=True)
    sku_code: str = Field(unique=True, index=True)
    description: str
    brand: str
    category: SkuCategory
    uom: Uom
    case_qty: int
    velocity_class: VelocityClass


class Location(SQLModel, table=True):
    __tablename__ = "location"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)  # zone-aisle-bay-level, e.g. A-03-12-1
    zone: str = Field(index=True)
    aisle: int
    bay: int
    level: int
    type: LocationType = Field(index=True)
    x: int  # floor map grid position
    y: int


class PickFace(SQLModel, table=True):
    __tablename__ = "pick_face"

    location_id: int = Field(foreign_key="location.id", primary_key=True)
    sku_id: int = Field(foreign_key="sku.id", unique=True)  # one pick face per SKU
    min_qty: int
    max_qty: int


class Inventory(SQLModel, table=True):
    __tablename__ = "inventory"

    id: int | None = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    sku_id: int = Field(foreign_key="sku.id", index=True)
    lpn: str | None = Field(default=None, unique=True)  # set for reserve pallets only
    qty: int
    received_at: NaiveDatetime


class Picker(SQLModel, table=True):
    __tablename__ = "picker"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    shift: Shift


class Order(SQLModel, table=True):
    __tablename__ = "orders"  # "order" is a reserved word in SQL

    id: int | None = Field(default=None, primary_key=True)
    order_number: str = Field(unique=True, index=True)
    customer: str
    created_at: NaiveDatetime
    ship_by: NaiveDatetime
    status: OrderStatus = Field(index=True)


class OrderLine(SQLModel, table=True):
    __tablename__ = "order_line"

    id: int | None = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="orders.id", index=True)
    sku_id: int = Field(foreign_key="sku.id", index=True)
    qty: int


class PickTask(SQLModel, table=True):
    __tablename__ = "pick_task"

    id: int | None = Field(default=None, primary_key=True)
    order_line_id: int = Field(foreign_key="order_line.id", index=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    picker_id: int | None = Field(default=None, foreign_key="picker.id")
    expected_qty: int
    picked_qty: int | None = None  # null until the task is done
    status: PickTaskStatus = Field(index=True)
    completed_at: NaiveDatetime | None = None


class ReplenishmentTask(SQLModel, table=True):
    __tablename__ = "replenishment_task"

    id: int | None = Field(default=None, primary_key=True)
    sku_id: int = Field(foreign_key="sku.id", index=True)
    from_location_id: int = Field(foreign_key="location.id")
    to_location_id: int = Field(foreign_key="location.id", index=True)
    lpn: str | None = None
    qty: int
    reason: str
    status: ReplenishmentStatus = Field(index=True)
    created_by: str
    approved_by: str | None = None
    created_at: NaiveDatetime
    decided_at: NaiveDatetime | None = None


class LogSource(StrEnum):
    """Who made a logged call."""

    CHAT = "CHAT"  # the in-app chat agent
    INVESTIGATOR = "INVESTIGATOR"  # the cycle count investigator
    MCP = "MCP"  # an MCP client such as Claude Desktop


class ModelCallLog(SQLModel, table=True):
    """One Claude request, with what it cost. Tool calls link to the request that asked for them.

    ``cost_usd`` is computed when the row is written, so later price changes don't
    rewrite history.
    """

    __tablename__ = "model_call_log"

    id: int | None = Field(default=None, primary_key=True)
    ts: NaiveDatetime
    session_id: str = Field(index=True)
    source: LogSource
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    stop_reason: str | None = None


class ToolCallLog(SQLModel, table=True):
    __tablename__ = "tool_call_log"

    id: int | None = Field(default=None, primary_key=True)
    ts: NaiveDatetime
    session_id: str = Field(index=True)
    source: LogSource = LogSource.MCP
    model_call_id: int | None = Field(default=None, foreign_key="model_call_log.id", index=True)
    tool: str
    args_json: str
    result_summary: str
    duration_ms: int
    approval: Approval = Approval.NOT_APPLICABLE


class InventoryTxn(SQLModel, table=True):
    """The inventory ledger: one row per stock change.

    For every location and SKU, the sum of ``qty_change`` equals the ``inventory`` qty.
    """

    __tablename__ = "inventory_txn"

    id: int | None = Field(default=None, primary_key=True)
    ts: NaiveDatetime = Field(index=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    sku_id: int = Field(foreign_key="sku.id", index=True)
    lpn: str | None = None
    qty_change: int
    type: TxnType = Field(index=True)
    user: str
    reason: str = ""  # free text; blank when nobody gave one
    ref: str | None = None  # what caused it, e.g. "pick_task:812"


class ShelfVariance(SQLModel, table=True):
    """Hidden truth for the cycle count simulation: what's physically there minus the system.

    Only the simulation and the evals read this. No tool, prompt or API response exposes it.
    ``transient`` rows are counting artefacts (a count in cases, a pick in progress) that a
    recount would not repeat.
    """

    __tablename__ = "shelf_variance"

    id: int | None = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    sku_id: int = Field(foreign_key="sku.id")
    lpn: str | None = None
    delta: int
    scenario: str
    transient: bool = False


class CycleCount(SQLModel, table=True):
    """One counted location and SKU. A mismatch is a discrepancy until someone resolves it."""

    __tablename__ = "cycle_count"

    id: int | None = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    sku_id: int = Field(foreign_key="sku.id")
    lpn: str | None = None
    counted_by: str
    counted_at: NaiveDatetime
    system_qty: int
    counted_qty: int
    variance: int  # counted - system
    status: CountStatus = Field(index=True)
    resolved_by: str | None = None
    resolved_at: NaiveDatetime | None = None
    resolution_reason: str | None = None


class Investigation(SQLModel, table=True):
    """The AI's explanation of one discrepancy: likely causes with evidence, and next steps."""

    __tablename__ = "investigation"

    id: int | None = Field(default=None, primary_key=True)
    cycle_count_id: int = Field(foreign_key="cycle_count.id", index=True)
    model: str
    status: InvestigationStatus = Field(index=True)
    summary: str | None = None
    causes_json: str = "[]"  # list of {cause, likelihood, evidence[]}
    next_steps_json: str = "[]"  # list of strings
    error: str | None = None
    tool_calls: int = 0
    started_at: NaiveDatetime
    finished_at: NaiveDatetime | None = None
