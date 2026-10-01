import json
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from tests.agent.fakes import FakeClient, refusal, text_reply, tool_reply
from tests.conftest import AS_OF, make_memory_engine
from warehouse_ops.agent.loop import (
    MAX_STEPS,
    MODEL,
    Agent,
    AgentStateError,
    Conversation,
)
from warehouse_ops.db.models import (
    Approval,
    ReplenishmentStatus,
    ReplenishmentTask,
    ToolCallLog,
)
from warehouse_ops.db.seed import seed_database
from warehouse_ops.services.replenishment import list_replenishment_needs


@pytest.fixture
def engine() -> Engine:
    # A fresh database per test, because these tests create tasks and log rows.
    engine = make_memory_engine()
    seed_database(engine, seed=42, as_of=AS_OF)
    return engine


def make_agent(engine: Engine, client: FakeClient) -> Agent:
    return Agent(client.as_anthropic(), engine, now=lambda: AS_OF)


def create_args(engine: Engine, **overrides: Any) -> dict[str, Any]:
    """Valid create_replenishment_task input for a face that needs stock."""
    with Session(engine) as session:
        need = next(
            n
            for n in list_replenishment_needs(session)
            if n.source and n.open_task_id is None and n.suggested_qty > 0
        )
    assert need.source is not None
    args: dict[str, Any] = {
        "sku_code": need.sku_code,
        "from_location": need.source.location,
        "to_location": need.location,
        "qty": need.suggested_qty,
        "reason": "empty pick face",
    }
    return args | overrides


def tool_results(request: dict[str, Any]) -> list[dict[str, Any]]:
    """The tool_result blocks in the last user message of a request."""
    last = request["messages"][-1]
    assert last["role"] == "user"
    return [b for b in last["content"] if b["type"] == "tool_result"]


def tasks(engine: Engine) -> list[ReplenishmentTask]:
    with Session(engine) as session:
        return list(session.exec(select(ReplenishmentTask)).all())


def logs(engine: Engine) -> list[ToolCallLog]:
    with Session(engine) as session:
        return list(session.exec(select(ToolCallLog)).all())


def test_read_tool_then_answer(engine: Engine) -> None:
    client = FakeClient(
        tool_reply(("tu_1", "list_replenishment_needs", {"zone": "A"})),
        text_reply("Zone A has 7 faces to refill."),
    )
    conversation = Conversation()
    turn = make_agent(engine, client).send(conversation, "What needs replenishing in A?")

    assert turn.status == "done"
    assert turn.reply == "Zone A has 7 faces to refill."
    assert [t.tool for t in turn.tool_calls] == ["list_replenishment_needs"]
    assert turn.tool_calls[0].ok

    first, second = client.messages.requests
    assert first["model"] == MODEL
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert {t["name"] for t in first["tools"]} >= {"find_stock", "create_replenishment_task"}
    assert "[Warehouse time: 2026-06-01 13:00]" in first["messages"][0]["content"]

    (result,) = tool_results(second)
    assert result["tool_use_id"] == "tu_1" and not result["is_error"]
    assert all(row["zone"] == "A" for row in json.loads(result["content"]))

    roles = [m["role"] for m in conversation.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert logs(engine)[-1].tool == "list_replenishment_needs"


def test_write_waits_for_approval_then_creates_an_approved_task(engine: Engine) -> None:
    args = create_args(engine)
    client = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", args), text="I'll refill it."),
        text_reply("Done: task created."),
    )
    agent = make_agent(engine, client)
    conversation = Conversation()
    before = len(tasks(engine))

    turn = agent.send(conversation, "Refill it")
    assert turn.status == "needs_approval"
    assert turn.reply == "I'll refill it."
    assert [(p.tool, p.input) for p in turn.pending] == [("create_replenishment_task", args)]
    assert len(tasks(engine)) == before  # nothing written yet
    assert len(client.messages.requests) == 1  # loop paused

    turn = agent.resolve(conversation, approve=True, decided_by="Pat")
    assert turn.status == "done" and turn.reply == "Done: task created."

    created = tasks(engine)[-1]
    assert len(tasks(engine)) == before + 1
    assert created.status == ReplenishmentStatus.APPROVED
    assert (created.created_by, created.approved_by) == ("agent", "Pat")
    (result,) = tool_results(client.messages.requests[1])
    assert json.loads(result["content"])["status"] == "APPROVED"
    assert logs(engine)[-1].approval == Approval.APPROVED


def test_rejection_writes_nothing_and_tells_claude(engine: Engine) -> None:
    client = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", create_args(engine))),
        text_reply("OK, I won't create it."),
    )
    agent = make_agent(engine, client)
    conversation = Conversation()
    before = len(tasks(engine))

    agent.send(conversation, "Refill it")
    turn = agent.resolve(conversation, approve=False, decided_by="Pat")

    assert turn.reply == "OK, I won't create it."
    assert len(tasks(engine)) == before
    (result,) = tool_results(client.messages.requests[1])
    assert "Pat rejected this action" in result["content"]
    assert logs(engine)[-1].approval == Approval.REJECTED
    assert turn.tool_calls[0].approval == Approval.REJECTED


def test_reads_and_writes_in_one_response_return_together(engine: Engine) -> None:
    args = create_args(engine)
    client = FakeClient(
        tool_reply(
            ("tu_read", "find_stock", {"sku_code": args["sku_code"]}),
            ("tu_write", "create_replenishment_task", args),
        ),
        text_reply("Done."),
    )
    agent = make_agent(engine, client)
    conversation = Conversation()

    turn = agent.send(conversation, "Check and refill")
    assert turn.status == "needs_approval"
    assert [t.tool for t in turn.tool_calls] == ["find_stock"]  # read already ran

    agent.resolve(conversation, approve=True, decided_by="Pat")
    results = tool_results(client.messages.requests[1])
    assert [r["tool_use_id"] for r in results] == ["tu_read", "tu_write"]


def test_rule_violation_is_an_error_result(engine: Engine) -> None:
    client = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", create_args(engine, qty=100_000))),
        text_reply("That's more than fits."),
    )
    agent = make_agent(engine, client)
    conversation = Conversation()
    before = len(tasks(engine))

    agent.send(conversation, "Refill it all")
    turn = agent.resolve(conversation, approve=True, decided_by="Pat")

    (result,) = tool_results(client.messages.requests[1])
    assert result["is_error"] and "Error:" in result["content"]
    assert len(tasks(engine)) == before
    assert not turn.tool_calls[0].ok


def test_invalid_tool_input_is_an_error_result(engine: Engine) -> None:
    client = FakeClient(
        tool_reply(("tu_1", "find_stock", {})),
        tool_reply(("tu_2", "no_such_tool", {})),
        text_reply("Sorry."),
    )
    make_agent(engine, client).send(Conversation(), "Where is it?")

    (missing_field,) = tool_results(client.messages.requests[1])
    assert missing_field["is_error"] and "sku_code" in missing_field["content"]
    (unknown,) = tool_results(client.messages.requests[2])
    assert unknown["is_error"] and "Unknown tool" in unknown["content"]


def test_state_errors(engine: Engine) -> None:
    client = FakeClient(tool_reply(("tu_1", "create_replenishment_task", create_args(engine))))
    agent = make_agent(engine, client)
    conversation = Conversation()

    with pytest.raises(AgentStateError, match="Nothing is waiting"):
        agent.resolve(conversation, approve=True, decided_by="Pat")
    agent.send(conversation, "Refill it")
    with pytest.raises(AgentStateError, match="pending action"):
        agent.send(conversation, "Something else")


def test_refusal_keeps_history_valid(engine: Engine) -> None:
    client = FakeClient(refusal())
    conversation = Conversation()
    turn = make_agent(engine, client).send(conversation, "...")
    assert turn.reply == "I can't help with that request."
    assert [m["role"] for m in conversation.messages] == ["user"]


def test_max_tokens_is_flagged(engine: Engine) -> None:
    client = FakeClient(text_reply("Partial answer", stop_reason="max_tokens"))
    turn = make_agent(engine, client).send(Conversation(), "Tell me everything")
    assert turn.reply.startswith("Partial answer") and "cut off" in turn.reply


def test_runaway_loop_stops(engine: Engine) -> None:
    looping = [tool_reply((f"tu_{i}", "find_stock", {"sku_code": "1"})) for i in range(MAX_STEPS)]
    client = FakeClient(*looping)
    turn = make_agent(engine, client).send(Conversation(), "Loop forever")
    assert "too many steps" in turn.reply
    assert len(client.messages.requests) == MAX_STEPS
