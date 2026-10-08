"""Running one tool call from Claude: validate, call the service, log it.

Shared by the chat agent and the cycle count investigator.
"""

import json
import time
from typing import Any

from anthropic.types.beta import BetaToolResultBlockParam, BetaToolUseBlock
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine
from sqlmodel import Session

from warehouse_ops.agent.tools import ToolContext, ToolSpec
from warehouse_ops.db.engine import readonly_session
from warehouse_ops.db.models import Approval, LogSource
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.tool_log import record_tool_call, summarize


class ToolTrace(BaseModel):
    tool: str
    input: dict[str, Any]
    ok: bool
    summary: str
    approval: Approval = Approval.NOT_APPLICABLE


def execute_tool_call(
    engine: Engine,
    tools: dict[str, ToolSpec],
    call: BetaToolUseBlock,
    ctx: ToolContext,
    *,
    session_id: str,
    source: LogSource,
    model_call_id: int | None = None,
    approval: Approval = Approval.NOT_APPLICABLE,
) -> tuple[BetaToolResultBlockParam, ToolTrace]:
    """Run ``call`` and return the tool_result for Claude plus a trace for the UI.

    Read tools get a read-only session; write tools commit only if the service succeeds.
    Bad input, unknown names and broken rules come back as error results Claude can read.
    """
    started = time.perf_counter()
    args = dict(call.input)
    spec = tools.get(call.name)
    content: str
    try:
        if spec is None:
            raise NotFoundError(f"Unknown tool {call.name!r}")
        parsed = spec.input_model.model_validate(args)
        if spec.writes:
            with Session(engine) as session:
                result = spec.run(session, parsed, ctx)
                session.commit()
        else:
            with readonly_session(engine) as session:
                result = spec.run(session, parsed, ctx)
        content = to_json(result)
        summary, ok = summarize(result), True
    except (NotFoundError, RuleViolationError, ValidationError) as exc:
        content = f"Error: {exc}"
        summary, ok = f"error: {exc}"[:200], False

    record_tool_call(
        engine,
        session_id=session_id,
        tool=call.name,
        args=args,
        summary=summary,
        duration_ms=round((time.perf_counter() - started) * 1000),
        approval=approval,
        source=source,
        model_call_id=model_call_id,
    )
    trace = ToolTrace(tool=call.name, input=args, ok=ok, summary=summary, approval=approval)
    block: BetaToolResultBlockParam = {
        "type": "tool_result",
        "tool_use_id": call.id,
        "content": content,
        "is_error": not ok,
    }
    return block, trace


def to_json(result: BaseModel | list[Any]) -> str:
    if isinstance(result, BaseModel):
        return result.model_dump_json()
    return json.dumps([r.model_dump(mode="json") for r in result])
