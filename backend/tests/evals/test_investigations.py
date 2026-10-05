"""The investigator eval suite: cases, ground truth and scoring (no API calls)."""

from typing import Any

import pytest
from sqlalchemy import Engine

from tests.agent.fakes import FakeClient, refusal, tool_reply
from tests.conftest import AS_OF
from warehouse_ops.agent.investigator import INVESTIGATION_TOOLS
from warehouse_ops.db.models import InvestigationStatus
from warehouse_ops.evals.common import seeded_engine
from warehouse_ops.evals.investigations import (
    InvestigationCase,
    ObservedInvestigation,
    case_placeholders,
    load_investigation_cases,
    prepare,
    resolve_case,
    run_investigation_case,
    run_investigation_evals,
    score_investigation,
    summarize_investigations,
)
from warehouse_ops.services.cycle_counts import Cause, InvestigationOut

MODEL = "claude-sonnet-5-5"


@pytest.fixture(scope="module")
def prepared() -> tuple[Engine, dict[str, Any], dict[str, int]]:
    engine = seeded_engine()
    facts, count_ids = prepare(engine)
    return engine, facts, count_ids


def findings(
    *causes: tuple[str, str, list[str]], summary: str = "", steps: list[str] | None = None
) -> InvestigationOut:
    return InvestigationOut(
        id=1,
        status=InvestigationStatus.DONE,
        model=MODEL,
        summary=summary,
        causes=[Cause(cause=c, likelihood=lik, evidence=ev) for c, lik, ev in causes],  # type: ignore[arg-type]
        next_steps=steps or [],
        error=None,
        tool_calls=2,
        started_at=AS_OF,
        finished_at=AS_OF,
    )


BLANK = InvestigationCase(
    id="blank",
    location="A-02-23-1",
    expect_tools=["get_inventory_history"],
    top_cause_any=[["adjust"]],
    evidence_contains=["Mcguire", "30"],
    next_steps_any=[["Mcguire", "ask"]],
)
SHRINK = InvestigationCase(
    id="shrink",
    location="A-03-24-1",
    top_likelihood_not=["high"],
    summary_any=[["no evidence", "unexplained"]],
)


def test_shipped_cases_cover_every_planted_discrepancy(
    prepared: tuple[Engine, dict[str, Any], dict[str, int]],
) -> None:
    _, facts, count_ids = prepared
    cases = load_investigation_cases()
    assert len(cases) == 8
    for case in cases:
        missing = case_placeholders(case) - set(facts)
        assert not missing, f"{case.id} uses unknown placeholders {missing}"
        resolved = resolve_case(case, facts)
        assert resolved.location in count_ids, f"{case.id}: no discrepancy at {resolved.location}"
        for expected in resolved.expect_tools:
            options = [expected] if isinstance(expected, str) else expected
            assert set(options) <= set(INVESTIGATION_TOOLS), f"{case.id} names unknown tools"
    resolved_locations = {resolve_case(c, facts).location for c in cases}
    assert resolved_locations == set(count_ids)  # one case per discrepancy, none missed


def test_facts_come_from_the_planted_scenarios(
    prepared: tuple[Engine, dict[str, Any], dict[str, int]],
) -> None:
    _, facts, _ = prepared
    assert facts["blank_qty"] == "30" and facts["blank_user_last"] in str(facts["blank_user"])
    assert facts["mis_slot_missing"] != facts["mis_slot_found"]
    assert str(facts["short_face"]).endswith("-1") and not str(facts["short_pallet"]).endswith("-1")


def test_a_good_investigation_passes() -> None:
    observed = ObservedInvestigation(
        ["get_inventory_history"],
        findings(
            ("Mistaken manual adjustment", "high", ["May 30: +30 by Michael Mcguire, no reason"]),
            summary="A +30 adjustment with a blank reason.",
            steps=["Ask Michael Mcguire about it"],
        ),
    )
    score = score_investigation(BLANK, observed)
    assert score.passed and score.failures == []
    assert (score.root_cause_ok, score.top3_ok, score.evidence_ok) == (True, True, True)


def test_the_right_cause_in_second_place_misses_top_1_but_counts_for_top_3() -> None:
    observed = ObservedInvestigation(
        ["get_inventory_history"],
        findings(
            ("Theft", "medium", ["nothing"]),
            ("Mistaken adjustment", "medium", ["+30 by Mcguire"]),
            steps=["Ask Mcguire"],
        ),
    )
    score = score_investigation(BLANK, observed)
    assert score.root_cause_ok is False and score.top3_ok is True and not score.passed


def test_missing_evidence_tools_and_steps_are_each_reported() -> None:
    observed = ObservedInvestigation([], findings(("A wrong adjustment", "high", ["no detail"])))
    score = score_investigation(BLANK, observed)
    assert score.root_cause_ok is True
    assert (score.evidence_ok, score.tools_ok, score.steps_ok) == (False, False, False)
    assert any("never called get_inventory_history" in f for f in score.failures)


def test_no_evidence_cases_reward_humility() -> None:
    humble = findings(("Damage or theft", "low", []), summary="No evidence in the ledger.")
    confident = findings(("Theft by a picker", "high", []), summary="Unexplained loss.")
    assert score_investigation(SHRINK, ObservedInvestigation([], humble)).passed
    score = score_investigation(SHRINK, ObservedInvestigation([], confident))
    assert score.root_cause_ok is False and "rated 'high'" in score.failures[0]


def test_a_failed_investigation_scores_zero() -> None:
    failed = findings().model_copy(update={"status": InvestigationStatus.FAILED, "error": "boom"})
    score = score_investigation(BLANK, ObservedInvestigation([], failed))
    assert not score.passed and "FAILED" in score.failures[0]


def test_runs_a_case_with_the_real_investigator(
    prepared: tuple[Engine, dict[str, Any], dict[str, int]],
) -> None:
    engine, facts, count_ids = prepared
    case = resolve_case(load_investigation_cases()[0], facts)  # blank-adjustment
    submit = {
        "summary": f"A +{facts['blank_qty']} adjustment by {facts['blank_user']}, no reason.",
        "causes": [
            {
                "cause": "Mistaken manual adjustment",
                "likelihood": "high",
                "evidence": [f"ADJUSTMENT +{facts['blank_qty']} by {facts['blank_user']}"],
            }
        ],
        "next_steps": [f"Ask {facts['blank_user']}"],
    }
    client = FakeClient(
        tool_reply(("tu_1", "get_inventory_history", {"location": case.location})),
        tool_reply(("tu_2", "submit_findings", submit)),
    )

    result = run_investigation_case(
        case, client=client.as_anthropic(), engine=engine, model=MODEL, count_ids=count_ids
    )

    assert result.status == "passed", result.failures
    assert result.tools == ["get_inventory_history"]
    assert result.input_tokens == 20 and result.cost_usd > 0  # metered from the fake usage


def test_errors_and_the_summary() -> None:
    cases = [BLANK.model_copy(update={"location": "A-02-23-1"})]
    results = run_investigation_evals(
        cases, client=FakeClient(refusal()).as_anthropic(), model=MODEL
    )
    assert results[0].status == "error" and results[0].error == "The model declined"

    summary = summarize_investigations(MODEL, results)
    assert (summary.cases, summary.errors, summary.passed) == (1, 1, 0)
    assert summary.root_cause_accuracy == 0.0


def test_excluded_claims_fail_the_top_cause() -> None:
    case = InvestigationCase(
        id="shrink",
        location="A-03-24-1",
        top_cause_any=[["lost"]],
        top_cause_excludes=["replenish"],
    )
    honest = findings(("Three units lost without a record", "high", ["no picks or adjustments"]))
    invented = findings(("Lost during a replenishment", "high", []))
    assert score_investigation(case, ObservedInvestigation([], honest)).passed
    score = score_investigation(case, ObservedInvestigation([], invented))
    assert score.root_cause_ok is False and "claims ['replenish']" in score.failures[0]
