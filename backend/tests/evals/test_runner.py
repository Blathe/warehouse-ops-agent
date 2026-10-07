from typing import Any

import anthropic
import httpx2
import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from tests.agent.fakes import FakeClient, text_reply, tool_reply
from tests.conftest import AS_OF, make_memory_engine
from warehouse_ops.agent.models import MODEL_OPTIONS
from warehouse_ops.agent.pricing import cost_usd
from warehouse_ops.db.seed import seed_database
from warehouse_ops.evals.cases import EvalCase, ExpectedCall
from warehouse_ops.evals.runner import (
    CaseResult,
    format_result,
    run_case,
    run_evals,
    summarize,
)
from warehouse_ops.services.replenishment import list_replenishment_needs

MODEL = "claude-opus-5-5"


@pytest.fixture
def engine() -> Engine:
    engine = make_memory_engine()
    seed_database(engine, seed=42, as_of=AS_OF)
    return engine


def create_args(engine: Engine, **overrides: Any) -> dict[str, Any]:
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


def test_read_case_passes_and_meters_usage(engine: Engine) -> None:
    client = FakeClient(
        tool_reply(("tu_1", "list_short_picks", {"zone": "A"})),
        text_reply("There are short picks in zone A."),
    )
    case = EvalCase(
        id="short",
        question="Any short picks in zone A?",
        expect_calls=[ExpectedCall(tool="list_short_picks", args={"zone": "A"})],
        answer_contains=["zone A"],
    )

    result = run_case(case, client=client.as_anthropic(), engine=engine, model=MODEL)

    assert result.status == "passed"
    assert result.calls == [{"tool": "list_short_picks", "args": {"zone": "A"}}]
    assert result.input_tokens == 20 and result.output_tokens == 20  # two scripted model calls
    assert result.cost_usd == pytest.approx(cost_usd(MODEL, 20, 20))
    assert result.seconds >= 0


def test_failed_check_is_reported_with_the_reason(engine: Engine) -> None:
    client = FakeClient(text_reply("Sure, here you go."))
    case = EvalCase(
        id="x", question="Where is SKU 1?", expect_calls=[ExpectedCall(tool="find_stock")]
    )

    result = run_case(case, client=client.as_anthropic(), engine=engine, model=MODEL)

    assert result.status == "failed"
    assert result.failures == ["never called find_stock"]
    assert "never called find_stock" in format_result(result)


def test_write_is_only_proposed_unless_the_case_approves(engine: Engine) -> None:
    args = create_args(engine)
    client = FakeClient(tool_reply(("tu_1", "create_replenishment_task", args)))
    case = EvalCase(
        id="propose",
        question="Move stock",
        expect_calls=[ExpectedCall(tool="create_replenishment_task", args={"qty": args["qty"]})],
        expect_task_created=False,
    )

    result = run_case(case, client=client.as_anthropic(), engine=engine, model=MODEL)

    assert result.status == "passed"  # proposed with the right qty, and nothing was created


def test_approved_write_creates_a_task(engine: Engine) -> None:
    client = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", create_args(engine))),
        text_reply("Done."),
    )
    case = EvalCase(id="e2e", question="Move stock", approve_writes=True, expect_task_created=True)

    result = run_case(case, client=client.as_anthropic(), engine=engine, model=MODEL)

    assert result.status == "passed"


def test_service_rules_still_refuse_an_approved_over_max_write(engine: Engine) -> None:
    client = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", create_args(engine, qty=100000))),
        text_reply("The system refused that."),
    )
    case = EvalCase(
        id="over-max", question="Move lots", approve_writes=True, expect_task_created=False
    )

    result = run_case(case, client=client.as_anthropic(), engine=engine, model=MODEL)

    assert result.status == "passed"


def test_api_failure_is_an_error_not_a_failure(engine: Engine) -> None:
    class BrokenMessages:
        def create(self, **_: Any) -> Any:
            request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIConnectionError(request=request)

    client = FakeClient()
    client.beta.messages = BrokenMessages()  # type: ignore[assignment]
    case = EvalCase(id="x", question="q")

    result = run_case(case, client=client.as_anthropic(), engine=engine, model=MODEL)

    assert result.status == "error"
    assert result.error is not None and "APIConnectionError" in result.error


def test_run_evals_reseeds_after_a_writing_case() -> None:
    # Facts are built from the seeded database; the second case must still find a free face.
    probe = make_memory_engine()
    seed_database(probe, seed=42, as_of=AS_OF)
    args = create_args(probe)
    cases = [
        EvalCase(id="writes", question="Move stock", approve_writes=True, expect_task_created=True),
        EvalCase(id="clean", question="Move stock again", expect_task_created=False),
    ]
    client = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", args)),
        text_reply("Done."),
        text_reply("Nothing to do."),
    )
    seen: list[str] = []

    results = run_evals(
        cases, client=client.as_anthropic(), model=MODEL, on_result=lambda r: seen.append(r.id)
    )

    assert [r.status for r in results] == ["passed", "passed"]  # no leftover task from case 1
    assert seen == ["writes", "clean"]


def test_summary_rates_ignore_checks_a_case_did_not_make() -> None:
    results = [
        CaseResult(
            id="a",
            question="q",
            status="passed",
            tool_ok=True,
            args_ok=True,
            seconds=1,
            cost_usd=0.01,
        ),
        CaseResult(
            id="b",
            question="q",
            status="failed",
            tool_ok=True,
            args_ok=False,
            seconds=3,
            cost_usd=0.02,
        ),
        CaseResult(
            id="c",
            question="q",
            status="failed",
            tool_ok=False,
            answer_ok=False,
            seconds=2,
            cost_usd=0.03,
        ),
        CaseResult(id="d", question="q", status="error", error="boom"),
    ]

    summary = summarize(MODEL, results)

    assert (summary.passed, summary.failed, summary.errors) == (1, 2, 1)
    assert summary.tool_selection_accuracy == pytest.approx(2 / 3)
    assert summary.argument_accuracy == 0.5
    assert summary.answer_accuracy == 0.0
    assert summary.outcome_accuracy is None
    assert summary.total_cost_usd == pytest.approx(0.06)
    assert summary.max_seconds == 3


def test_cost_uses_the_model_price_table() -> None:
    option = next(m for m in MODEL_OPTIONS if m.id == MODEL)
    assert cost_usd(MODEL, 1_000_000, 0) == option.input_per_mtok
    assert cost_usd(MODEL, 0, 1_000_000) == option.output_per_mtok
