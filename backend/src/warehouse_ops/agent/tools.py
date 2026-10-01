"""The agent's tools: Claude-facing definitions wrapped around the same services.

Each tool has a Pydantic input model. Its JSON schema is what Claude sees, and the
same model validates whatever Claude sends back before a service runs.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from anthropic.types.beta import BetaToolParam
from pydantic import BaseModel, Field
from sqlmodel import Session

from warehouse_ops.services import inventory, picking, replenishment, replenishment_tasks
from warehouse_ops.services.schemas import LocalDateTime, Zone


@dataclass(frozen=True)
class ToolContext:
    now: datetime
    # Set only when a person approved this call; write tools use it to approve the task.
    approved_by: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    run: Callable[[Session, Any, ToolContext], BaseModel | list[Any]]
    writes: bool = False

    def to_param(self) -> BetaToolParam:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


class ListShortPicksInput(BaseModel):
    since: LocalDateTime | None = Field(
        None, description="Start time, e.g. 2026-06-01T06:00. Defaults to 24 hours ago."
    )
    zone: Zone | None = Field(None, description="Only this zone.")
    sku_code: str | None = Field(None, description="Only this SKU code.")


class FindStockInput(BaseModel):
    sku_code: str = Field(description="The SKU code, e.g. 10442.")


class ListReplenishmentNeedsInput(BaseModel):
    zone: Zone | None = Field(None, description="Only this zone.")
    include_open_demand: bool = Field(
        True, description="Also flag faces holding less than their open pick tasks need."
    )


class CreateReplenishmentTaskInput(BaseModel):
    sku_code: str = Field(description="The SKU to move, e.g. 10442.")
    from_location: str = Field(description="Reserve location holding the pallet, e.g. A-03-12-3.")
    to_location: str = Field(description="The SKU's pick face, e.g. A-03-12-1.")
    qty: int = Field(gt=0, description="Units to move.")
    reason: str = Field(description="Why, e.g. 'empty after 3 short picks'.")


def _create_task(
    session: Session, args: CreateReplenishmentTaskInput, ctx: ToolContext
) -> BaseModel:
    task = replenishment_tasks.create_replenishment_task(
        session,
        sku_code=args.sku_code,
        from_location=args.from_location,
        to_location=args.to_location,
        qty=args.qty,
        reason=args.reason,
        created_by="agent",
        now=ctx.now,
    )
    if ctx.approved_by:
        task = replenishment_tasks.decide_replenishment_task(
            session, task_id=task.task_id, approve=True, decided_by=ctx.approved_by, now=ctx.now
        )
    return task


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="list_short_picks",
            description=(
                "List short picks: completed pick tasks where the picker found less than "
                "expected. Newest first, with order, location, SKU, expected vs picked qty "
                "and picker. A short pick usually means the pick face ran out before it "
                "was replenished."
            ),
            input_model=ListShortPicksInput,
            run=lambda s, a, ctx: picking.list_short_picks(
                s, now=ctx.now, since=a.since, zone=a.zone, sku_code=a.sku_code
            ),
        ),
        ToolSpec(
            name="find_stock",
            description=(
                "Show where a SKU is stocked: its pick face (on-hand, min, max) and every "
                "reserve pallet (location, LPN, qty, received date), oldest pallet first."
            ),
            input_model=FindStockInput,
            run=lambda s, a, ctx: inventory.find_stock(s, a.sku_code),
        ),
        ToolSpec(
            name="list_replenishment_needs",
            description=(
                "List pick faces that need replenishment, most urgent (empty) first. Each "
                "item has on-hand vs min/max, open pick demand, a suggested qty in whole "
                "cases, the oldest reserve pallet to pull from (null source = no reserve "
                "stock, so it cannot be replenished) and any task already open for it."
            ),
            input_model=ListReplenishmentNeedsInput,
            run=lambda s, a, ctx: replenishment.list_replenishment_needs(
                s, zone=a.zone, include_open_demand=a.include_open_demand
            ),
        ),
        ToolSpec(
            name="create_replenishment_task",
            description=(
                "Create a replenishment task: move qty of a SKU from a reserve pallet to its "
                "pick face. The app shows the user an approval card before this runs, so "
                "call it directly when the user wants stock moved; don't ask for "
                "confirmation in text first. Refused if the source isn't a reserve slot "
                "holding the SKU, qty is more than the pallet holds or would put the face "
                "over its max, or a task is already open for that face."
            ),
            input_model=CreateReplenishmentTaskInput,
            run=_create_task,
            writes=True,
        ),
    ]
}
