"""MCP server exposing the warehouse tools.

Run from backend/:  python -m uv run warehouse-mcp   (stdio, for Claude Desktop or any MCP client)

Each tool is a thin wrapper: open a session (read-only unless the tool writes), call a
service, log the call.
Docstrings and parameter descriptions become the tool descriptions the model reads,
so they are written for the model.
"""

import time
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import uuid4

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy import Engine
from sqlmodel import Session

from warehouse_ops import clock
from warehouse_ops.db.engine import get_engine, readonly_session
from warehouse_ops.services import inventory, picking, replenishment, replenishment_tasks
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.schemas import (
    LocalDateTime,
    ReplenishmentNeed,
    ReplenishmentTaskOut,
    ShortPick,
    StockReport,
    Zone,
)
from warehouse_ops.tool_log import WAREHOUSE_CONTEXT, record_tool_call, summarize

INSTRUCTIONS = "Tools for the warehouse. " + WAREHOUSE_CONTEXT

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# Not destructive (it only adds a PROPOSED task), but clients still ask the user first.
WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)


def create_server(engine: Engine, now: Callable[[], datetime] = clock.now) -> MCPServer:
    """Build the server around an engine (tests pass an in-memory one)."""
    server = MCPServer(name="warehouse-ops", instructions=INSTRUCTIONS)
    session_id = uuid4().hex

    def logged[T](
        tool: str, args: dict[str, Any], call: Callable[[Session], T], *, writes: bool = False
    ) -> T:
        """Run ``call`` in a session and record it in tool_call_log.

        Read tools get a read-only session; a write tool's session is committed only if
        the service succeeds.
        """
        started = time.perf_counter()
        summary = "error"
        try:
            if writes:
                with Session(engine) as session:
                    result = call(session)
                    session.commit()
            else:
                with readonly_session(engine) as session:
                    result = call(session)
            summary = summarize(result)
            return result
        except (NotFoundError, RuleViolationError) as exc:
            summary = f"error: {exc}"
            raise ToolError(str(exc)) from exc
        finally:
            record_tool_call(
                engine,
                ts=now(),
                session_id=session_id,
                tool=tool,
                args=args,
                summary=summary,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )

    @server.tool(annotations=READ_ONLY)
    def list_short_picks(
        since: Annotated[
            LocalDateTime | None,
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

    @server.tool(annotations=WRITE)
    def create_replenishment_task(
        sku_code: Annotated[str, Field(description="The SKU to move, e.g. 10442.")],
        from_location: Annotated[
            str, Field(description="Reserve location holding the pallet, e.g. A-03-12-3.")
        ],
        to_location: Annotated[str, Field(description="The SKU's pick face, e.g. A-03-12-1.")],
        qty: Annotated[int, Field(description="Units to move.", gt=0)],
        reason: Annotated[str, Field(description="Why, e.g. 'empty after 3 short picks'.")],
    ) -> ReplenishmentTaskOut:
        """Propose a replenishment task: move qty of a SKU from a reserve pallet to its pick face.

        Only call this after the user has agreed to the specific move. The task is created
        as PROPOSED and does nothing until a supervisor approves it in the app; you cannot
        approve it. It is refused if the source isn't a reserve slot holding the SKU, qty is
        more than the pallet holds or would put the face over its max, or a task is already
        open for that face. Use list_replenishment_needs for suggested moves.
        """
        args = {
            "sku_code": sku_code,
            "from_location": from_location,
            "to_location": to_location,
            "qty": qty,
            "reason": reason,
        }
        return logged(
            "create_replenishment_task",
            args,
            lambda s: replenishment_tasks.create_replenishment_task(
                s,
                sku_code=sku_code,
                from_location=from_location,
                to_location=to_location,
                qty=qty,
                reason=reason,
                created_by="mcp",
                now=now(),
            ),
            writes=True,
        )

    return server


def main() -> None:
    create_server(get_engine()).run()
