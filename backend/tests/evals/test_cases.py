from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from tests.conftest import AS_OF
from warehouse_ops.agent.tools import TOOLS
from warehouse_ops.db.seed import SeedSummary
from warehouse_ops.evals.cases import (
    EvalCase,
    ExpectedCall,
    load_cases,
    placeholders,
    resolve,
)
from warehouse_ops.evals.truth import build_facts


def test_shipped_cases_load_and_use_real_tools() -> None:
    cases = load_cases()
    assert len(cases) >= 10
    for case in cases:
        unknown = case.referenced_tools() - set(TOOLS)
        assert not unknown, f"{case.id} references unknown tools {unknown}"


def test_every_placeholder_is_a_known_fact(seeded: tuple[Engine, SeedSummary]) -> None:
    with Session(seeded[0]) as session:
        facts = build_facts(session, AS_OF)
    for case in load_cases():
        missing = placeholders(case) - set(facts)
        assert not missing, f"{case.id} uses unknown placeholders {missing}"
        resolve(case, facts)  # fills every placeholder without raising


def test_facts_describe_the_seeded_data(seeded: tuple[Engine, SeedSummary]) -> None:
    with Session(seeded[0]) as session:
        facts = build_facts(session, AS_OF)
    assert isinstance(facts["need_qty"], int) and facts["need_qty"] > 0
    assert facts["unknown_sku"] != facts["need_sku"]
    assert facts["stockout_sku"] != facts["need_sku"]


def test_resolve_keeps_the_type_of_a_whole_token() -> None:
    case = EvalCase(
        id="x",
        question="Move {qty} of {sku}",
        expect_calls=[ExpectedCall(tool="t", args={"qty": "{qty}", "note": "sku {sku}"})],
    )
    resolved = resolve(case, {"qty": 48, "sku": "10442"})
    assert resolved.question == "Move 48 of 10442"
    assert resolved.expect_calls[0].args == {"qty": 48, "note": "sku 10442"}


def test_unknown_yaml_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - id: a\n    question: q\n    expect_cals: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "cases:\n  - id: a\n    question: q\n  - id: a\n    question: r\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(path)
