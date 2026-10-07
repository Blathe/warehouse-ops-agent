"""Recording tool calls in tool_call_log (shared by the MCP server and the agent)."""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session

from warehouse_ops import clock
from warehouse_ops.agent.pricing import cost_usd
from warehouse_ops.db.models import Approval, LogSource, ModelCallLog, ToolCallLog

WAREHOUSE_CONTEXT = """\
The warehouse is a fishing tackle distribution centre. Zone A holds small tackle (lures,
soft plastics, hooks, line), zone B rods and reels, zone C bulky gear (coolers, nets,
waders, electronics). Each SKU has one pick face (level 1) with a min/max, refilled
from full pallets in reserve locations (levels 2-3). Location codes are
zone-aisle-bay-level, e.g. A-03-12-1. Times are warehouse local time."""


def summarize(result: object) -> str:
    """A short description of a tool result for the log."""
    if isinstance(result, list):
        return f"{len(result)} results"
    if isinstance(result, BaseModel):
        return result.model_dump_json()[:200]
    return str(result)[:200]


def record_model_call(
    engine: Engine,
    *,
    ts: datetime | None = None,
    session_id: str,
    source: LogSource,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
    stop_reason: str | None,
) -> int:
    """Record one Claude request and its cost; returns the row id for tool calls to link to.

    ``ts`` defaults to the real time (see ``clock.wall_now``).
    """
    with Session(engine) as session:
        row = ModelCallLog(
            ts=ts or clock.wall_now(),
            session_id=session_id,
            source=source,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd(model, input_tokens, output_tokens),
            duration_ms=duration_ms,
            stop_reason=stop_reason,
        )
        session.add(row)
        session.commit()
        assert row.id is not None
        return row.id


def record_tool_call(
    engine: Engine,
    *,
    ts: datetime | None = None,
    session_id: str,
    tool: str,
    args: dict[str, Any],
    summary: str,
    duration_ms: int,
    approval: Approval = Approval.NOT_APPLICABLE,
    source: LogSource = LogSource.MCP,
    model_call_id: int | None = None,
) -> None:
    with Session(engine) as session:
        session.add(
            ToolCallLog(
                ts=ts or clock.wall_now(),
                session_id=session_id,
                source=source,
                model_call_id=model_call_id,
                tool=tool,
                args_json=json.dumps(args, default=str),
                result_summary=summary,
                duration_ms=duration_ms,
                approval=approval,
            )
        )
        session.commit()
