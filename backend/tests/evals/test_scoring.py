from typing import Any

from warehouse_ops.evals.cases import EvalCase, ExpectedCall
from warehouse_ops.evals.scoring import Observed, ObservedCall, score_case


def observed(*calls: tuple[str, dict[str, Any]], answer: str = "", task: bool = False) -> Observed:
    return Observed([ObservedCall(t, a) for t, a in calls], answer, task)


def case(**fields: Any) -> EvalCase:
    return EvalCase(id="c", question="q", **fields)


def test_expected_tool_called_with_matching_args_passes() -> None:
    c = case(expect_calls=[ExpectedCall(tool="list_short_picks", args={"zone": "A"})])
    score = score_case(c, observed(("list_short_picks", {"zone": "a", "since": "2026-06-01"})))
    assert score.passed
    assert score.tool_ok and score.args_ok


def test_wrong_argument_fails_args_but_not_tool_selection() -> None:
    c = case(expect_calls=[ExpectedCall(tool="find_stock", args={"sku_code": "111"})])
    score = score_case(c, observed(("find_stock", {"sku_code": "222"})))
    assert score.tool_ok is True
    assert score.args_ok is False
    assert not score.passed


def test_missing_tool_fails_selection() -> None:
    c = case(expect_calls=[ExpectedCall(tool="find_stock")])
    score = score_case(c, observed(("list_short_picks", {})))
    assert not score.tool_ok
    assert score.args_ok is None  # no args were specified, so none were judged


def test_any_of_tools_accepts_either() -> None:
    c = case(expect_calls=[ExpectedCall(tool=["find_stock", "list_replenishment_needs"])])
    assert score_case(c, observed(("list_replenishment_needs", {}))).passed
    assert not score_case(c, observed(("list_short_picks", {}))).passed


def test_numbers_compare_equal_to_their_text() -> None:
    c = case(expect_calls=[ExpectedCall(tool="create_replenishment_task", args={"qty": 48})])
    assert score_case(c, observed(("create_replenishment_task", {"qty": "48"}))).passed


def test_forbidden_tool_fails() -> None:
    c = case(forbid_tools=["create_replenishment_task"])
    score = score_case(c, observed(("create_replenishment_task", {})))
    assert not score.tool_ok
    assert score_case(c, observed(("find_stock", {}))).passed


def test_expect_no_tools() -> None:
    c = case(expect_no_tools=True)
    assert score_case(c, observed(answer="I can only help with the warehouse.")).passed
    assert not score_case(c, observed(("find_stock", {}))).passed


def test_answer_checks_are_case_insensitive() -> None:
    c = case(
        answer_contains=["A-03-12-1"],
        answer_contains_any=[["no reserve", "out of stock"]],
        answer_excludes=["approved"],
    )
    assert score_case(c, observed(answer="Face a-03-12-1 is OUT OF STOCK.")).passed

    score = score_case(c, observed(answer="Face A-03-12-1 is fine and approved."))
    assert score.answer_ok is False
    assert len(score.failures) == 2  # missing the any-group, and an excluded word


def test_outcome_must_match() -> None:
    c = case(expect_task_created=False)
    assert score_case(c, observed(task=False)).passed
    score = score_case(c, observed(task=True))
    assert score.outcome_ok is False
    assert not score.passed
