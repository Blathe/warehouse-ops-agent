"""Scoring: compare what the agent did and said with what a case expects.

Pure functions, so they're tested without any model calls.
"""

from dataclasses import dataclass, field
from typing import Any

from warehouse_ops.evals.cases import EvalCase


@dataclass(frozen=True)
class ObservedCall:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Observed:
    calls: list[ObservedCall]  # tools the agent called, plus writes it proposed
    answer: str
    task_created: bool  # a replenishment task made by the agent exists afterwards


@dataclass(frozen=True)
class CaseScore:
    """Each check is True/False, or None when the case doesn't make that kind of check."""

    tool_ok: bool
    args_ok: bool | None
    answer_ok: bool | None
    outcome_ok: bool | None
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(
            check is not False for check in (self.tool_ok, self.args_ok, self.answer_ok)
        ) and (self.outcome_ok is not False)


def _same(expected: Any, actual: Any) -> bool:
    return str(expected).strip().lower() == str(actual).strip().lower()


def _args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return all(key in actual and _same(value, actual[key]) for key, value in expected.items())


def score_case(case: EvalCase, observed: Observed) -> CaseScore:
    failures: list[str] = []
    called = {call.tool for call in observed.calls}

    # Tool selection
    tool_ok = True
    for expected in case.expect_calls:
        if not called.intersection(expected.tools):
            tool_ok = False
            failures.append(f"never called {' or '.join(expected.tools)}")
    for tool in case.forbid_tools:
        if tool in called:
            tool_ok = False
            failures.append(f"called {tool}, which it shouldn't")
    if case.expect_no_tools and called:
        tool_ok = False
        failures.append(f"called {', '.join(sorted(called))} but no tool was needed")

    # Arguments: only judged for expected calls that name arguments
    args_ok: bool | None = None
    for expected in case.expect_calls:
        if not expected.args:
            continue
        args_ok = args_ok is not False
        matching = [c for c in observed.calls if c.tool in expected.tools]
        if not any(_args_match(expected.args, c.args) for c in matching):
            args_ok = False
            failures.append(f"no {' or '.join(expected.tools)} call had args {expected.args}")

    # Answer text
    answer = observed.answer.lower()
    answer_ok: bool | None = None
    if case.answer_contains or case.answer_contains_any or case.answer_excludes:
        answer_ok = True
        for text in case.answer_contains:
            if text.lower() not in answer:
                answer_ok = False
                failures.append(f"answer is missing {text!r}")
        for group in case.answer_contains_any:
            if not any(text.lower() in answer for text in group):
                answer_ok = False
                failures.append(f"answer has none of {group}")
        for text in case.answer_excludes:
            if text.lower() in answer:
                answer_ok = False
                failures.append(f"answer contains {text!r}")

    # Outcome in the database
    outcome_ok: bool | None = None
    if case.expect_task_created is not None:
        outcome_ok = observed.task_created == case.expect_task_created
        if not outcome_ok:
            wanted = "created" if case.expect_task_created else "not created"
            failures.append(f"expected the task to be {wanted}")

    return CaseScore(tool_ok, args_ok, answer_ok, outcome_ok, failures)
