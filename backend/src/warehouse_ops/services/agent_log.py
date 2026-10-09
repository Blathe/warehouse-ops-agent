"""Reading the agent log: what Claude (and MCP clients) did, and what it cost.

Two tables back this: ``tool_call_log`` (one row per tool call) and ``model_call_log``
(one row per Claude request, with its cost). A tool call links to the request that asked
for it, so a request that asks for three tools shows its cost once, not three times.
Everything here is read-only.
"""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import ColumnElement
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, func, select

from warehouse_ops.db.models import Approval, LogSource, ModelCallLog, ToolCallLog
from warehouse_ops.services.schemas import LocalDateTime

MAX_RESULTS = 200
DEFAULT_LIMIT = 50


class ToolCallEntry(BaseModel):
    id: int
    ts: LocalDateTime
    session_id: str
    source: LogSource
    tool: str
    args: dict[str, Any]
    result_summary: str
    result: str | None  # the full result text, None for rows logged before it was kept
    duration_ms: int
    approval: Approval
    model_call_id: int | None
    model: str | None  # the model that asked for this call, when known
    model_call_cost_usd: float | None  # shared by every call from the same response


class ModelCallEntry(BaseModel):
    id: int
    ts: LocalDateTime
    session_id: str
    source: LogSource
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    stop_reason: str | None


class LogStep(BaseModel):
    """One Claude response and the tool calls it asked for.

    ``model_call`` is None for calls with no response behind them (MCP clients).
    """

    model_call: ModelCallEntry | None
    tool_calls: list[ToolCallEntry]


class CostBreakdown(BaseModel):
    key: str
    cost_usd: float
    model_calls: int
    tool_calls: int


class LogSummary(BaseModel):
    total_cost_usd: float
    model_calls: int
    tool_calls: int
    sessions: int
    input_tokens: int
    output_tokens: int
    by_model: list[CostBreakdown]
    by_source: list[CostBreakdown]


class SessionSummary(BaseModel):
    session_id: str
    source: LogSource
    started_at: LocalDateTime
    last_at: LocalDateTime
    model_calls: int
    tool_calls: int
    cost_usd: float
    rejected: int


def _window(
    ts: Any,
    source: Any,
    *,
    source_filter: LogSource | None,
    since: datetime | None,
    until: datetime | None,
) -> list[ColumnElement[bool]]:
    """The source / time-range conditions, for either log table."""
    conditions: list[ColumnElement[bool]] = []
    if source_filter is not None:
        conditions.append(source == source_filter)
    if since is not None:
        conditions.append(ts >= since)
    if until is not None:
        conditions.append(ts <= until)
    return conditions


def _tool_entry(row: ToolCallLog, model_call: ModelCallLog | None) -> ToolCallEntry:
    assert row.id is not None
    return ToolCallEntry(
        id=row.id,
        ts=row.ts,
        session_id=row.session_id,
        source=row.source,
        tool=row.tool,
        args=json.loads(row.args_json),
        result_summary=row.result_summary,
        result=row.result_text,
        duration_ms=row.duration_ms,
        approval=row.approval,
        model_call_id=row.model_call_id,
        model=model_call.model if model_call else None,
        model_call_cost_usd=model_call.cost_usd if model_call else None,
    )


def _model_entry(row: ModelCallLog) -> ModelCallEntry:
    assert row.id is not None
    return ModelCallEntry(
        id=row.id,
        ts=row.ts,
        session_id=row.session_id,
        source=row.source,
        model=row.model,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        duration_ms=row.duration_ms,
        stop_reason=row.stop_reason,
    )


def list_tool_calls(
    session: Session,
    *,
    session_id: str | None = None,
    tool: str | None = None,
    source: LogSource | None = None,
    approval: Approval | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_id: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[ToolCallEntry]:
    """Tool calls, newest first. Pass the last id you got as ``before_id`` for the next page."""
    where = _window(
        ToolCallLog.ts, ToolCallLog.source, source_filter=source, since=since, until=until
    )
    query = (
        select(ToolCallLog, ModelCallLog)
        .join(ModelCallLog, col(ToolCallLog.model_call_id) == col(ModelCallLog.id), isouter=True)
        .where(*where)
        .order_by(col(ToolCallLog.id).desc())
        .limit(min(max(limit, 1), MAX_RESULTS))
    )
    if session_id is not None:
        query = query.where(ToolCallLog.session_id == session_id)
    if tool is not None:
        query = query.where(ToolCallLog.tool == tool)
    if approval is not None:
        query = query.where(ToolCallLog.approval == approval)
    if before_id is not None:
        query = query.where(col(ToolCallLog.id) < before_id)
    return [_tool_entry(row, model_call) for row, model_call in session.exec(query).all()]


def summarize_log(
    session: Session,
    *,
    source: LogSource | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> LogSummary:
    """Totals for the page header.

    Cost lives on model calls, so tool and approval filters don't apply here.
    """
    model_where = _window(
        ModelCallLog.ts, ModelCallLog.source, source_filter=source, since=since, until=until
    )
    tool_where = _window(
        ToolCallLog.ts, ToolCallLog.source, source_filter=source, since=since, until=until
    )

    cost, model_calls, input_tokens, output_tokens = session.exec(
        select(
            func.coalesce(func.sum(ModelCallLog.cost_usd), 0.0),
            func.count(),
            func.coalesce(func.sum(ModelCallLog.input_tokens), 0),
            func.coalesce(func.sum(ModelCallLog.output_tokens), 0),
        ).where(*model_where)
    ).one()
    tool_calls = session.exec(
        select(func.count()).select_from(ToolCallLog).where(*tool_where)
    ).one()
    sessions = {
        *session.exec(select(ModelCallLog.session_id).where(*model_where).distinct()).all(),
        *session.exec(select(ToolCallLog.session_id).where(*tool_where).distinct()).all(),
    }

    by_model = [
        CostBreakdown(key=model, cost_usd=c, model_calls=n, tool_calls=0)
        for model, c, n in session.exec(
            select(ModelCallLog.model, func.sum(ModelCallLog.cost_usd), func.count())
            .where(*model_where)
            .group_by(ModelCallLog.model)
        ).all()
    ]
    by_source = {
        s: CostBreakdown(key=s.value, cost_usd=0.0, model_calls=0, tool_calls=0) for s in LogSource
    }
    for src, c, n in session.exec(
        select(col(ModelCallLog.source), func.sum(ModelCallLog.cost_usd), func.count())
        .where(*model_where)
        .group_by(ModelCallLog.source)
    ).all():
        by_source[src].cost_usd, by_source[src].model_calls = c, n
    for src, n in session.exec(
        select(col(ToolCallLog.source), func.count())
        .where(*tool_where)
        .group_by(ToolCallLog.source)
    ).all():
        by_source[src].tool_calls = n

    return LogSummary(
        total_cost_usd=cost,
        model_calls=model_calls,
        tool_calls=tool_calls,
        sessions=len(sessions),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        by_model=sorted(by_model, key=lambda b: -b.cost_usd),
        by_source=[b for b in by_source.values() if b.model_calls or b.tool_calls],
    )


def list_sessions(
    session: Session,
    *,
    source: LogSource | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> list[SessionSummary]:
    """One row per conversation, investigation or MCP connection, most recent first."""
    found: dict[str, SessionSummary] = {}

    def add(
        session_id: str,
        src: LogSource,
        first: datetime,
        last: datetime,
        *,
        model_calls: int = 0,
        tool_calls: int = 0,
        cost: float = 0.0,
        rejected: int = 0,
    ) -> None:
        current = found.get(session_id)
        if current is None:
            found[session_id] = SessionSummary(
                session_id=session_id,
                source=src,
                started_at=first,
                last_at=last,
                model_calls=model_calls,
                tool_calls=tool_calls,
                cost_usd=cost,
                rejected=rejected,
            )
            return
        current.started_at = min(current.started_at, first)
        current.last_at = max(current.last_at, last)
        current.model_calls += model_calls
        current.tool_calls += tool_calls
        current.cost_usd += cost
        current.rejected += rejected

    model_where = _window(
        ModelCallLog.ts, ModelCallLog.source, source_filter=source, since=since, until=until
    )
    for sid, src, first, last, n, cost in session.execute(
        sa_select(
            col(ModelCallLog.session_id),
            col(ModelCallLog.source),
            func.min(ModelCallLog.ts),
            func.max(ModelCallLog.ts),
            func.count(),
            func.sum(ModelCallLog.cost_usd),
        )
        .where(*model_where)
        .group_by(ModelCallLog.session_id, col(ModelCallLog.source))
    ).all():
        add(sid, src, first, last, model_calls=n, cost=cost)

    tool_where = _window(
        col(ToolCallLog.ts), col(ToolCallLog.source), source_filter=source, since=since, until=until
    )
    for sid, src, first, last, n in session.execute(
        sa_select(
            col(ToolCallLog.session_id),
            col(ToolCallLog.source),
            func.min(ToolCallLog.ts),
            func.max(ToolCallLog.ts),
            func.count(),
        )
        .where(*tool_where)
        .group_by(ToolCallLog.session_id, col(ToolCallLog.source))
    ).all():
        add(sid, src, first, last, tool_calls=n)
    for sid, n in session.exec(
        select(ToolCallLog.session_id, func.count())
        .where(*tool_where, ToolCallLog.approval == Approval.REJECTED)
        .group_by(ToolCallLog.session_id)
    ).all():
        found[sid].rejected = n

    ordered = sorted(found.values(), key=lambda s: (s.last_at, s.session_id), reverse=True)
    return ordered[offset : offset + min(max(limit, 1), MAX_RESULTS)]


def get_session_steps(session: Session, session_id: str) -> list[LogStep]:
    """A session in order: each Claude request with the tool calls it asked for."""
    model_calls = session.exec(
        select(ModelCallLog)
        .where(ModelCallLog.session_id == session_id)
        .order_by(col(ModelCallLog.id))
    ).all()
    tool_rows = session.exec(
        select(ToolCallLog)
        .where(ToolCallLog.session_id == session_id)
        .order_by(col(ToolCallLog.id))
    ).all()

    by_id = {m.id: m for m in model_calls}
    grouped: dict[int, list[ToolCallEntry]] = {}
    steps: list[tuple[datetime, bool, int, LogStep]] = []
    for row in tool_rows:
        parent = by_id.get(row.model_call_id)
        entry = _tool_entry(row, parent)
        if parent is None:
            steps.append((row.ts, True, row.id or 0, LogStep(model_call=None, tool_calls=[entry])))
        else:
            grouped.setdefault(parent.id or 0, []).append(entry)
    for m in model_calls:
        step = LogStep(model_call=_model_entry(m), tool_calls=grouped.get(m.id or 0, []))
        steps.append((m.ts, False, m.id or 0, step))
    # Model calls and standalone tool calls have separate id sequences, so order by time,
    # with a request before the standalone calls that share its timestamp.
    steps.sort(key=lambda s: s[:3])
    return [s[3] for s in steps]
