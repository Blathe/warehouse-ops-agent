"""MCP server exposing the warehouse tools.

Run from backend/:  python -m uv run warehouse-mcp   (stdio, for Claude Desktop or any MCP client)

Each tool is a thin wrapper: open a read-only session, call a service, log the call.
Docstrings and parameter descriptions become the tool descriptions the model reads,
so they are written for the model.
"""

import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session

from warehouse_ops import clock
from warehouse_ops.db.engine import get_engine, readonly_session
from warehouse_ops.db.models import ToolCallLog
from warehouse_ops.services import inventory, picking, replenishment
from warehouse_ops.services.errors import NotFoundError
from warehouse_ops.services.schemas import ReplenishmentNeed, ShortPick, StockReport

INSTRUCTIONS = """\
Tools for a fishing tackle distribution warehouse. Zone A holds small tackle (lures,
soft plastics, hooks, line), zone B rods and reels, zone C bulky gear (coolers, nets,
waders, electronics). Each SKU has one pick face (level 1) with a min/max, refilled
from full pallets in reserve locations (levels 2-3). Location codes are
zone-aisle-bay-level, e.g. A-03-12-1. Times are warehouse local time."""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

Zone = Literal["A", "B", "C"]


def create_server(engine: Engine, now: Callable[[], datetime] = clock.now) -> MCPServer:
    """Build the server around an engine (tests pass an in-memory one)."""
    server = MCPServer(name="warehouse-ops", instructions=INSTRUCTIONS)
    session_id = uuid4().hex

    def logged[T](tool: str, args: dict[str, Any], call: Callable[[Session], T]) -> T:
        """Run ``call`` in a read-only session and record it in tool_call_log."""
        started = time.perf_counter()
        summary = "error"
        try:
            with readonly_session(engine) as session:
                result = call(session)
            summary = _summarize(result)
            return result
        except NotFoundError as exc:
            summary = f"error: {exc}"
            raise ToolError(str(exc)) from exc
        finally:
            with Session(engine) as session:
                session.add(
                    ToolCallLog(
                        ts=now(),
                        session_id=session_id,
                        tool=tool,
                        args_json=json.dumps(args, default=str),
                        result_summary=summary,
                        duration_ms=round((time.perf_counter() - started) * 1000),
                    )
                )
                session.commit()

    @server.tool(annotations=READ_ONLY)
    def list_short_picks(
        since: Annotated[
            datetime | None,
            Field(description="Start time, e.g. 2026-06-01T06:00. Defaults to 24 hours ago."),
        ] = None,
        zone: Annotated[Zone | None, Field(description="Only this zone.")] = None,
        sku_code: Annotated[str | None, Field(description="Only this SKU code.")] = None,
    ) -> list[ShortPick]:
        """List short picks: completed pick tasks where the picker found less than expected.

        Newest first, with order, location, SKU, expected vs picked qty and picker.
        A short pick usually means the pick face ran out before it was replenished.
        """
        args = {"since": since, "zone": zone, "sku_code": sku_code}
        return logged(
            "list_short_picks",
            args,
            lambda s: picking.list_short_picks(
                s, now=now(), since=since, zone=zone, sku_code=sku_code
            ),
        )

    @server.tool(annotations=READ_ONLY)
    def find_stock(
        sku_code: Annotated[str, Field(description="The SKU code, e.g. 10442.")],
    ) -> StockReport:
        """Show where a SKU is stocked: its pick face (on-hand, min, max) and every reserve
        pallet (location, LPN, qty, received date), oldest pallet first."""
        return logged(
            "find_stock",
            {"sku_code": sku_code},
            lambda s: inventory.find_stock(s, sku_code),
        )

    @server.tool(annotations=READ_ONLY)
    def list_replenishment_needs(
        zone: Annotated[Zone | None, Field(description="Only this zone.")] = None,
        include_open_demand: Annotated[
            bool,
            Field(description="Also flag faces holding less than their open pick tasks need."),
        ] = True,
    ) -> list[ReplenishmentNeed]:
        """List pick faces that need replenishment, most urgent (empty) first.

        Each item has on-hand vs min/max, open pick demand, a suggested qty in whole
        cases, the oldest reserve pallet to pull from (null source = no reserve stock,
        so it cannot be replenished), and any replenishment task already open for it.
        """
        args = {"zone": zone, "include_open_demand": include_open_demand}
        return logged(
            "list_replenishment_needs",
            args,
            lambda s: replenishment.list_replenishment_needs(
                s, zone=zone, include_open_demand=include_open_demand
            ),
        )

    return server


def _summarize(result: object) -> str:
    if isinstance(result, list):
        return f"{len(result)} results"
    if isinstance(result, BaseModel):
        return result.model_dump_json()[:200]
    return str(result)[:200]


def main() -> None:
    create_server(get_engine()).run()
