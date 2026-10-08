"""The investigator, driven by a scripted fake Claude client (no API calls)."""

from random import Random
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from tests.agent.fakes import FakeClient, refusal, text_reply, tool_reply
from tests.conftest import AS_OF, make_memory_engine
from warehouse_ops.agent.investigator import (
    DEFAULT_INVESTIGATOR_MODEL,
    TOOL_PARAMS,
    Investigator,
)
from warehouse_ops.db.models import InvestigationStatus, LogSource, ModelCallLog, ToolCallLog
from warehouse_ops.db.seed import seed_database
from warehouse_ops.services.cycle_counts import CycleCountOut, simulate_cycle_count

FINDINGS: dict[str, Any] = {
    "summary": "A +30 adjustment with no reason was keyed here; the shelf never had the units.",
    "causes": [
        {
            "cause": "Mistaken manual adjustment",
            "likelihood": "high",
            "evidence": ["2026-05-30 18:39 ADJUSTMENT +30 by Michael Mcguire, blank reason"],
        }
    ],
    "next_steps": ["Ask Michael Mcguire about the adjustment", "Accept the count"],
}


@pytest.fixture
def engine() -> Engine:
    engine = make_memory_engine()
    seed_database(engine, seed=42, as_of=AS_OF)
    return engine


def open_discrepancy(engine: Engine) -> CycleCountOut:
    with Session(engine) as session:
        run = simulate_cycle_count(session, rng=Random(1), now=AS_OF)
        session.commit()
    return next(d for d in run.discrepancies if d.location == "A-02-23-1")


def start(engine: Engine, client: FakeClient, count: CycleCountOut) -> tuple[Investigator, int]:
    investigator = Investigator(client.as_anthropic(), engine, now=lambda: AS_OF)
    with Session(engine) as session:
        investigation_id = investigator.start(session, count.id)
        session.commit()
    return investigator, investigation_id


def test_investigates_with_tools_then_submits_findings(engine: Engine) -> None:
    count = open_discrepancy(engine)
    client = FakeClient(
        tool_reply(("tu_1", "get_inventory_history", {"location": "A-02-23-1"})),
        tool_reply(("tu_2", "submit_findings", FINDINGS)),
    )
    investigator, investigation_id = start(engine, client, count)

    result = investigator.run(investigation_id)

    assert result.status == InvestigationStatus.DONE
    assert result.summary == FINDINGS["summary"]
    assert result.causes[0].likelihood == "high" and result.next_steps == FINDINGS["next_steps"]
    assert result.tool_calls == 1 and result.model == DEFAULT_INVESTIGATOR_MODEL

    first, second = client.messages.requests
    assert first["model"] == DEFAULT_INVESTIGATOR_MODEL
    assert {t["name"] for t in first["tools"]} == {t["name"] for t in TOOL_PARAMS}
    assert "A-02-23-1" in first["messages"][0]["content"]
    history = second["messages"][-1]["content"][0]
    assert not history["is_error"] and '"qty_change": 30' in history["content"]

    with Session(engine) as session:
        logged = session.exec(
            select(ToolCallLog).where(ToolCallLog.session_id == f"investigation:{investigation_id}")
        ).all()
    assert [log.tool for log in logged] == ["get_inventory_history"]


def test_the_investigator_cannot_write(engine: Engine) -> None:
    names = {t["name"] for t in TOOL_PARAMS}
    assert "create_replenishment_task" not in names
    count = open_discrepancy(engine)
    client = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", {"sku_code": "1"})),
        tool_reply(("tu_2", "submit_findings", FINDINGS)),
    )
    investigator, investigation_id = start(engine, client, count)

    investigator.run(investigation_id)

    rejected = client.messages.requests[1]["messages"][-1]["content"][0]
    assert rejected["is_error"] and "Unknown tool" in rejected["content"]


def test_invalid_findings_get_a_second_chance(engine: Engine) -> None:
    count = open_discrepancy(engine)
    client = FakeClient(
        tool_reply(("tu_1", "submit_findings", {"summary": "missing the rest"})),
        tool_reply(("tu_2", "submit_findings", FINDINGS)),
    )
    investigator, investigation_id = start(engine, client, count)

    assert investigator.run(investigation_id).status == InvestigationStatus.DONE
    retry = client.messages.requests[1]["messages"][-1]["content"][0]
    assert retry["is_error"] and "Invalid findings" in retry["content"]


def test_plain_text_answer_is_kept_as_the_summary(engine: Engine) -> None:
    count = open_discrepancy(engine)
    investigator, investigation_id = start(engine, FakeClient(text_reply("Probably theft.")), count)
    result = investigator.run(investigation_id)
    assert result.status == InvestigationStatus.DONE and result.summary == "Probably theft."


@pytest.mark.parametrize(
    ("client", "error"),
    [
        (FakeClient(refusal()), "declined"),
        (FakeClient(), "more model calls"),  # the fake raises: no reply scripted
    ],
)
def test_failures_are_recorded_not_raised(engine: Engine, client: FakeClient, error: str) -> None:
    count = open_discrepancy(engine)
    investigator, investigation_id = start(engine, client, count)
    result = investigator.run(investigation_id)
    assert result.status == InvestigationStatus.FAILED
    assert result.error is not None and error in result.error


def test_model_calls_are_logged_with_cost_and_linked_to_tool_calls(engine: Engine) -> None:
    count = open_discrepancy(engine)
    client = FakeClient(
        tool_reply(("tu_1", "get_inventory_history", {"location": "A-02-23-1"})),
        tool_reply(("tu_2", "submit_findings", FINDINGS)),
    )
    investigator, investigation_id = start(engine, client, count)
    investigator.run(investigation_id)

    with Session(engine) as session:
        first, second = session.exec(select(ModelCallLog)).all()
        (call,) = session.exec(select(ToolCallLog)).all()
    assert first.session_id == f"investigation:{investigation_id}"
    assert first.source == LogSource.INVESTIGATOR and first.cost_usd > 0
    assert second.stop_reason == "tool_use"
    assert (call.source, call.model_call_id) == (LogSource.INVESTIGATOR, first.id)
