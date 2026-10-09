"""Reading the agent log, against a small hand-built log in a fresh in-memory database."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel

from tests.conftest import AS_OF, make_memory_engine
from warehouse_ops.db.models import Approval, LogSource
from warehouse_ops.services import agent_log
from warehouse_ops.tool_log import record_model_call, record_tool_call


def at(minutes: int) -> datetime:
    return AS_OF + timedelta(minutes=minutes)


def model_call(
    engine: Engine,
    session_id: str,
    minute: int,
    *,
    source: LogSource = LogSource.CHAT,
    model: str = "claude-opus-5-5",
    input_tokens: int = 1000,
    output_tokens: int = 100,
) -> int:
    return record_model_call(
        engine,
        ts=at(minute),
        session_id=session_id,
        source=source,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=800,
        stop_reason="tool_use",
    )


def tool_call(
    engine: Engine,
    session_id: str,
    minute: int,
    tool: str = "find_stock",
    *,
    source: LogSource = LogSource.CHAT,
    model_call_id: int | None = None,
    approval: Approval = Approval.NOT_APPLICABLE,
) -> None:
    record_tool_call(
        engine,
        ts=at(minute),
        session_id=session_id,
        tool=tool,
        args={"sku_code": "10442"},
        summary="1 results",
        result='[{"sku_code": "10442"}]',
        duration_ms=12,
        approval=approval,
        source=source,
        model_call_id=model_call_id,
    )


@pytest.fixture
def engine() -> Engine:
    """Three sessions: a chat with a rejected write, an investigation, and an MCP client."""
    engine = make_memory_engine()
    SQLModel.metadata.create_all(engine)
    first = model_call(engine, "chat-1", 0)  # 1000 in + 100 out on Opus = $0.006
    tool_call(engine, "chat-1", 1, "find_stock", model_call_id=first)
    tool_call(engine, "chat-1", 1, "list_short_picks", model_call_id=first)
    second = model_call(engine, "chat-1", 2, input_tokens=2000, output_tokens=200)  # $0.012
    tool_call(
        engine,
        "chat-1",
        3,
        "create_replenishment_task",
        model_call_id=second,
        approval=Approval.REJECTED,
    )
    inv = model_call(
        engine,
        "investigation:7",
        10,
        source=LogSource.INVESTIGATOR,
        model="claude-sonnet-5-5",
        input_tokens=1_000_000,
        output_tokens=0,
    )  # $2
    tool_call(
        engine,
        "investigation:7",
        11,
        "get_inventory_history",
        source=LogSource.INVESTIGATOR,
        model_call_id=inv,
    )
    tool_call(engine, "mcp-1", 20, "find_stock", source=LogSource.MCP)
    return engine


def test_tool_calls_come_newest_first_with_the_cost_of_their_request(engine: Engine) -> None:
    with Session(engine) as session:
        entries = agent_log.list_tool_calls(session)

    assert [e.tool for e in entries] == [
        "find_stock",
        "get_inventory_history",
        "create_replenishment_task",
        "list_short_picks",
        "find_stock",
    ]
    mcp, investigation, rejected, parallel_a, parallel_b = entries
    assert mcp.model_call_id is None and mcp.model_call_cost_usd is None and mcp.model is None
    assert investigation.model == "claude-sonnet-5-5"
    assert investigation.model_call_cost_usd == pytest.approx(2.0)
    assert rejected.approval == Approval.REJECTED
    assert rejected.model_call_cost_usd == pytest.approx(0.012)
    # Parallel calls share one request, so the UI can count its cost once.
    assert parallel_a.model_call_id == parallel_b.model_call_id
    assert parallel_a.args == {"sku_code": "10442"}
    assert parallel_a.result == '[{"sku_code": "10442"}]'


def test_tool_call_filters(engine: Engine) -> None:
    with Session(engine) as session:

        def tools(**filters: object) -> list[str]:
            return [e.tool for e in agent_log.list_tool_calls(session, **filters)]  # type: ignore[arg-type]

        assert len(tools(session_id="chat-1")) == 3
        assert tools(tool="list_short_picks") == ["list_short_picks"]
        assert tools(source=LogSource.INVESTIGATOR) == ["get_inventory_history"]
        assert tools(approval=Approval.REJECTED) == ["create_replenishment_task"]
        assert tools(since=at(10), until=at(11)) == ["get_inventory_history"]


def test_pages_by_the_last_id_seen(engine: Engine) -> None:
    with Session(engine) as session:
        everything = agent_log.list_tool_calls(session)
        page_one = agent_log.list_tool_calls(session, limit=2)
        page_two = agent_log.list_tool_calls(session, limit=2, before_id=page_one[-1].id)
        page_three = agent_log.list_tool_calls(session, limit=2, before_id=page_two[-1].id)

    assert [e.id for e in page_one + page_two + page_three] == [e.id for e in everything]
    assert len(page_three) == 1


def test_summary_totals_cost_once_per_request(engine: Engine) -> None:
    with Session(engine) as session:
        summary = agent_log.summarize_log(session)

    assert summary.total_cost_usd == pytest.approx(0.006 + 0.012 + 2.0)
    assert (summary.model_calls, summary.tool_calls, summary.sessions) == (3, 5, 3)
    assert summary.input_tokens == 1000 + 2000 + 1_000_000
    assert summary.output_tokens == 300
    assert {b.key: b.cost_usd for b in summary.by_model} == pytest.approx(
        {"claude-opus-5-5": 0.018, "claude-sonnet-5-5": 2.0}
    )
    by_source = {b.key: b for b in summary.by_source}
    assert by_source["CHAT"].cost_usd == pytest.approx(0.018)
    assert (by_source["CHAT"].model_calls, by_source["CHAT"].tool_calls) == (2, 3)
    assert (by_source["MCP"].model_calls, by_source["MCP"].tool_calls) == (0, 1)
    assert by_source["MCP"].cost_usd == 0


def test_summary_follows_the_filters(engine: Engine) -> None:
    with Session(engine) as session:
        chat = agent_log.summarize_log(session, source=LogSource.CHAT)
        late = agent_log.summarize_log(session, since=at(10))
        empty = agent_log.summarize_log(session, since=at(1000))

    assert chat.total_cost_usd == pytest.approx(0.018) and chat.sessions == 1
    assert late.total_cost_usd == pytest.approx(2.0) and late.sessions == 2
    assert (empty.total_cost_usd, empty.model_calls, empty.tool_calls) == (0, 0, 0)
    assert empty.by_model == [] and empty.by_source == []


def test_sessions_are_grouped_and_most_recent_first(engine: Engine) -> None:
    with Session(engine) as session:
        sessions = agent_log.list_sessions(session)
        only_chat = agent_log.list_sessions(session, source=LogSource.CHAT)
        second_page = agent_log.list_sessions(session, limit=1, offset=1)

    assert [s.session_id for s in sessions] == ["mcp-1", "investigation:7", "chat-1"]
    mcp, investigation, chat = sessions
    assert (mcp.model_calls, mcp.tool_calls, mcp.cost_usd) == (0, 1, 0)
    assert investigation.source == LogSource.INVESTIGATOR
    assert investigation.cost_usd == pytest.approx(2.0)
    assert (chat.model_calls, chat.tool_calls, chat.rejected) == (2, 3, 1)
    assert chat.cost_usd == pytest.approx(0.018)
    assert (chat.started_at, chat.last_at) == (at(0), at(3))
    assert [s.session_id for s in only_chat] == ["chat-1"]
    assert [s.session_id for s in second_page] == ["investigation:7"]


def test_session_steps_group_tool_calls_under_their_request(engine: Engine) -> None:
    with Session(engine) as session:
        steps = agent_log.get_session_steps(session, "chat-1")
        mcp_steps = agent_log.get_session_steps(session, "mcp-1")
        missing = agent_log.get_session_steps(session, "nope")

    first, second = steps
    assert first.model_call is not None and first.model_call.cost_usd == pytest.approx(0.006)
    assert [c.tool for c in first.tool_calls] == ["find_stock", "list_short_picks"]
    assert second.model_call is not None
    assert [c.approval for c in second.tool_calls] == [Approval.REJECTED]
    # A call with no request behind it is its own step.
    (standalone,) = mcp_steps
    assert standalone.model_call is None and standalone.tool_calls[0].tool == "find_stock"
    assert missing == []


def test_a_long_result_is_cut_and_marked() -> None:
    from warehouse_ops.tool_log import MAX_RESULT_CHARS, result_text

    assert result_text("[]") == "[]"
    cut = result_text("x" * (MAX_RESULT_CHARS + 50))
    assert cut.startswith("x" * MAX_RESULT_CHARS) and cut.endswith("(truncated)")
