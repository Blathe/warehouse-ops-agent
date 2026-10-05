"""Eval cases: what a question should make the agent do, and how an answer is judged.

Cases live in ``backend/evals/cases.yaml``. Values that depend on the seeded data (a SKU
code, a location, a quantity) are written as ``{token}`` placeholders and filled in from
the database at run time (see ``truth.py``), so a case never goes stale when the seed changes.
"""

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

Facts = dict[str, str | int]

DEFAULT_CASES_PATH = Path(__file__).resolve().parents[3] / "evals" / "cases.yaml"

_WHOLE_TOKEN = re.compile(r"^\{(\w+)\}$")


class ExpectedCall(BaseModel):
    """A tool call the agent should make (or, for writes, propose)."""

    model_config = ConfigDict(extra="forbid")

    tool: str | list[str]  # a list means any one of these tools is acceptable
    args: dict[str, Any] = {}  # every key must match; other arguments are ignored

    @property
    def tools(self) -> list[str]:
        return [self.tool] if isinstance(self.tool, str) else self.tool


class EvalCase(BaseModel):
    # Reject unknown keys so a typo in the YAML fails loudly instead of silently skipping a check.
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    expect_calls: list[ExpectedCall] = []
    forbid_tools: list[str] = []
    expect_no_tools: bool = False
    answer_contains: list[str] = []  # every string must appear (case-insensitive)
    answer_contains_any: list[list[str]] = []  # each group needs at least one string to appear
    answer_excludes: list[str] = []  # none may appear
    approve_writes: bool = False  # let the runner approve proposed writes, to exercise the rules
    expect_task_created: bool | None = None  # check whether a replenishment task now exists

    def referenced_tools(self) -> set[str]:
        tools = set(self.forbid_tools)
        for call in self.expect_calls:
            tools.update(call.tools)
        return tools


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [EvalCase.model_validate(item) for item in raw["cases"]]
    ids = [case.id for case in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate case ids: {', '.join(duplicates)}")
    return cases


def placeholders(case: BaseModel) -> set[str]:
    """Every ``{token}`` the case uses."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.update(re.findall(r"\{(\w+)\}", value))
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(case.model_dump())
    return found


def resolve(case: EvalCase, facts: Facts) -> EvalCase:
    """Fill the case's ``{token}`` placeholders from ``facts``."""
    return EvalCase.model_validate(resolve_values(case.model_dump(), facts))


def resolve_values(value: Any, facts: Facts) -> Any:
    """Fill ``{token}`` placeholders anywhere in nested lists and dicts.

    A value that is exactly one token keeps the fact's own type, so ``qty: "{need_qty}"``
    becomes an int; a token inside a longer string is inserted as text.
    """
    if isinstance(value, str):
        whole = _WHOLE_TOKEN.match(value)
        if whole:
            return facts[whole.group(1)]
        return re.sub(r"\{(\w+)\}", lambda m: str(facts[m.group(1)]), value)
    if isinstance(value, list):
        return [resolve_values(item, facts) for item in value]
    if isinstance(value, dict):
        return {key: resolve_values(item, facts) for key, item in value.items()}
    return value
