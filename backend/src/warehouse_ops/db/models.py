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


class ToolCallLog(SQLModel, table=True):
    __tablename__ = "tool_call_log"

    id: int | None = Field(default=None, primary_key=True)
    ts: NaiveDatetime
    session_id: str = Field(index=True)
    tool: str
    args_json: str
    result_summary: str
    duration_ms: int
    approval: Approval = Approval.NOT_APPLICABLE
