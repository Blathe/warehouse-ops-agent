"""Evals for the cycle count investigator: does it find the true cause of each planted problem?

Run from backend/:  python -m uv run run-evals --suite investigator [--model ...] [--only ...]

One seeded database and one simulated count open a discrepancy for every planted scenario.
Each case investigates one of them with the real investigator and scores its findings
against the known cause. Investigations only read, so the cases share the database.
The ground truth (``shelf_variance``) is read here, in the evals, and never by the model.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

import yaml
from anthropic import Anthropic
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine
from sqlmodel import Session, col, select

from warehouse_ops.agent.investigator import Investigator
from warehouse_ops.db.models import (
    InventoryTxn,
    Location,
    PickTask,
    PickTaskStatus,
    ShelfVariance,
    Sku,
    ToolCallLog,
    TxnType,
)
from warehouse_ops.evals.cases import Facts, placeholders, resolve_values
from warehouse_ops.evals.common import AS_OF, Meter, MeteredClient, cost_usd, seeded_engine
from warehouse_ops.services.cycle_counts import (
    InvestigationOut,
    simulate_cycle_count,
)

DEFAULT_CASES_PATH = Path(__file__).resolve().parents[3] / "evals" / "investigations.yaml"
COUNT_SEED = 1  # the simulated count's random sample; planted locations are always counted


class InvestigationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in the YAML fails loudly

    id: str
    location: str  # the discrepancy to investigate
    expect_tools: list[str | list[str]] = []  # a list entry means any one of those tools
    top_cause_any: list[list[str]] = []
    any_cause_any: list[list[str]] = []
    evidence_contains: list[str] = []
    next_steps_any: list[list[str]] = []
    summary_any: list[list[str]] = []
    top_likelihood_not: list[str] = []


def load_investigation_cases(path: Path = DEFAULT_CASES_PATH) -> list[InvestigationCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [InvestigationCase.model_validate(item) for item in raw["cases"]]
    ids = [c.id for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate case ids: {', '.join(duplicates)}")
    return cases


def case_placeholders(case: InvestigationCase) -> set[str]:
    return placeholders(case)


def resolve_case(case: InvestigationCase, facts: Facts) -> InvestigationCase:
    return InvestigationCase.model_validate(resolve_values(case.model_dump(), facts))


# --- Ground truth -------------------------------------------------------------------------


def build_investigation_facts(session: Session) -> Facts:
    """Where each scenario was planted, and the facts a good investigation should cite."""

    def planted(scenario: str) -> list[ShelfVariance]:
        rows = session.exec(
            select(ShelfVariance)
            .where(ShelfVariance.scenario == scenario)
            .order_by(col(ShelfVariance.delta))
        ).all()
        if not rows:
            raise LookupError(f"The seed has no {scenario} scenario")
        return list(rows)

    def code(location_id: int) -> str:
        location = session.get(Location, location_id)
        assert location is not None
        return location.code

    (blank,) = planted("blank_adjustment")
    adjustment = session.exec(
        select(InventoryTxn).where(
            InventoryTxn.location_id == blank.location_id,
            InventoryTxn.type == TxnType.ADJUSTMENT,
            InventoryTxn.reason == "",
        )
    ).one()
    missing, found = planted("mis_slot")  # ordered by delta: the missing side is negative
    (case,) = planted("case_vs_each")
    case_sku = session.get(Sku, case.sku_id)
    assert case_sku is not None
    short_face, short_pallet = planted("short_replen")
    (mid,) = planted("mid_pick_count")
    pick = session.exec(
        select(PickTask).where(
            PickTask.location_id == mid.location_id,
            PickTask.status == PickTaskStatus.OPEN,
            PickTask.expected_qty == -mid.delta,
        )
    ).first()
    assert pick is not None
    (shrink,) = planted("unexplained_shrink")

    # Strings, since the cases match them as text in the findings.
    return {
        "blank_location": code(blank.location_id),
        "blank_qty": str(adjustment.qty_change),
        "blank_user": adjustment.user,
        "blank_user_last": adjustment.user.split()[-1],
        "mis_slot_missing": code(missing.location_id),
        "mis_slot_found": code(found.location_id),
        "mis_slot_lpn": missing.lpn or "",
        "case_location": code(case.location_id),
        "case_qty": str(case_sku.case_qty),
        "short_face": code(short_face.location_id),
        "short_pallet": code(short_pallet.location_id),
        "short_qty": str(-short_face.delta),
        "mid_pick_location": code(mid.location_id),
        "mid_pick_qty": str(pick.expected_qty),
        "shrink_location": code(shrink.location_id),
    }


# --- Scoring ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservedInvestigation:
    tools: list[str]
    findings: InvestigationOut


@dataclass(frozen=True)
class InvestigationScore:
    """Each check is True/False, or None when the case doesn't make it."""

    root_cause_ok: bool | None  # top cause matches (or, for no-evidence cases, it stays humble)
    top3_ok: bool | None
    evidence_ok: bool | None
    tools_ok: bool | None
    steps_ok: bool | None
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        checks = (self.root_cause_ok, self.top3_ok, self.evidence_ok, self.tools_ok, self.steps_ok)
        return all(check is not False for check in checks)


def _groups_match(groups: list[list[str]], text: str) -> list[list[str]]:
    """The groups with no match in ``text``."""
    lowered = text.lower()
    return [g for g in groups if not any(word.lower() in lowered for word in g)]


def score_investigation(
    case: InvestigationCase, observed: ObservedInvestigation
) -> InvestigationScore:
    failures: list[str] = []
    found = observed.findings
    causes = found.causes
    cause_text = [f"{c.cause} {' '.join(c.evidence)}" for c in causes]

    if found.status != "DONE":
        return InvestigationScore(
            False, None, None, None, None, [f"investigation {found.status}: {found.error}"]
        )

    root: bool | None = None
    if case.top_cause_any or case.top_likelihood_not or case.summary_any:
        root = True
        if case.top_cause_any:
            missing = (
                _groups_match(case.top_cause_any, cause_text[0]) if causes else case.top_cause_any
            )
            if missing:
                root = False
                failures.append(f"top cause mentions none of {missing[0]}")
        if case.top_likelihood_not and causes and causes[0].likelihood in case.top_likelihood_not:
            root = False
            failures.append(f"top cause rated {causes[0].likelihood!r} with no evidence")
        if case.summary_any:
            missing = _groups_match(case.summary_any, found.summary or "")
            if missing:
                root = False
                failures.append(f"summary mentions none of {missing[0]}")

    top3: bool | None = None
    groups = case.any_cause_any or case.top_cause_any
    if groups:
        top3 = any(not _groups_match(groups, text) for text in cause_text[:3])
        if not top3:
            failures.append("no cause in the top three matches")

    evidence: bool | None = None
    if case.evidence_contains:
        everything = " ".join([found.summary or "", *cause_text]).lower()
        absent = [e for e in case.evidence_contains if e.lower() not in everything]
        evidence = not absent
        if absent:
            failures.append(f"evidence doesn't cite {absent}")

    tools: bool | None = None
    if case.expect_tools:
        tools = True
        for expected in case.expect_tools:
            options = [expected] if isinstance(expected, str) else expected
            if not set(options) & set(observed.tools):
                tools = False
                failures.append(f"never called {' or '.join(options)}")

    steps: bool | None = None
    if case.next_steps_any:
        missing = _groups_match(case.next_steps_any, " ".join(found.next_steps))
        steps = not missing
        if missing:
            failures.append(f"next steps mention none of {missing[0]}")

    return InvestigationScore(root, top3, evidence, tools, steps, failures)


# --- Running ------------------------------------------------------------------------------


class InvestigationResult(BaseModel):
    id: str
    location: str
    status: str  # "passed", "failed" or "error"
    root_cause_ok: bool | None = None
    top3_ok: bool | None = None
    evidence_ok: bool | None = None
    tools_ok: bool | None = None
    steps_ok: bool | None = None
    failures: list[str] = []
    summary: str = ""
    causes: list[dict[str, object]] = []
    next_steps: list[str] = []
    tools: list[str] = []
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    error: str | None = None


class InvestigationSummary(BaseModel):
    suite: str = "investigator"
    model: str
    cases: int
    passed: int
    failed: int
    errors: int
    root_cause_accuracy: float | None
    top3_accuracy: float | None
    evidence_accuracy: float | None
    tool_use_accuracy: float | None
    next_step_accuracy: float | None
    total_cost_usd: float
    mean_seconds: float
    max_seconds: float


def prepare(engine: Engine) -> tuple[Facts, dict[str, int]]:
    """Simulate one count on the seeded database; returns the facts and count ids by location."""
    with Session(engine) as session:
        facts = build_investigation_facts(session)
        run = simulate_cycle_count(session, rng=Random(COUNT_SEED), now=AS_OF)
        session.commit()
    return facts, {d.location: d.id for d in run.discrepancies}


def run_investigation_case(
    case: InvestigationCase,
    *,
    client: Anthropic,
    engine: Engine,
    model: str,
    count_ids: dict[str, int],
) -> InvestigationResult:
    """Investigate the discrepancy at ``case.location`` and score the findings."""
    if case.location not in count_ids:
        return InvestigationResult(
            id=case.id,
            location=case.location,
            status="error",
            error=f"The simulated count opened no discrepancy at {case.location}",
        )
    meter = Meter()
    metered = MeteredClient(client, meter).as_anthropic()
    investigator = Investigator(metered, engine, now=lambda: AS_OF, model=model, parallel=1)
    with Session(engine) as session:
        investigation_id = investigator.start(session, count_ids[case.location])
        session.commit()
    findings = investigator.run(investigation_id)

    with Session(engine) as session:
        tools = list(
            session.exec(
                select(ToolCallLog.tool)
                .where(ToolCallLog.session_id == f"investigation:{investigation_id}")
                .order_by(col(ToolCallLog.id))
            ).all()
        )
    score = score_investigation(case, ObservedInvestigation(tools, findings))
    status = "error" if findings.status == "FAILED" else ("passed" if score.passed else "failed")
    return InvestigationResult(
        id=case.id,
        location=case.location,
        status=status,
        root_cause_ok=score.root_cause_ok,
        top3_ok=score.top3_ok,
        evidence_ok=score.evidence_ok,
        tools_ok=score.tools_ok,
        steps_ok=score.steps_ok,
        failures=score.failures,
        summary=findings.summary or "",
        causes=[c.model_dump() for c in findings.causes],
        next_steps=findings.next_steps,
        tools=tools,
        input_tokens=meter.input_tokens,
        output_tokens=meter.output_tokens,
        cost_usd=cost_usd(model, meter.input_tokens, meter.output_tokens),
        seconds=meter.seconds,
        error=findings.error,
    )


def run_investigation_evals(
    cases: list[InvestigationCase],
    *,
    client: Anthropic,
    model: str,
    on_result: Callable[[InvestigationResult], None] | None = None,
) -> list[InvestigationResult]:
    """Run every case on one seeded database with one simulated count."""
    engine = seeded_engine()
    facts, count_ids = prepare(engine)
    results = []
    for case in cases:
        result = run_investigation_case(
            resolve_case(case, facts),
            client=client,
            engine=engine,
            model=model,
            count_ids=count_ids,
        )
        results.append(result)
        if on_result:
            on_result(result)
    return results


def _rate(checks: list[bool | None]) -> float | None:
    made = [c for c in checks if c is not None]
    return sum(made) / len(made) if made else None


def summarize_investigations(
    model: str, results: list[InvestigationResult]
) -> InvestigationSummary:
    seconds = [r.seconds for r in results]
    return InvestigationSummary(
        model=model,
        cases=len(results),
        passed=sum(r.status == "passed" for r in results),
        failed=sum(r.status == "failed" for r in results),
        errors=sum(r.status == "error" for r in results),
        root_cause_accuracy=_rate([r.root_cause_ok for r in results]),
        top3_accuracy=_rate([r.top3_ok for r in results]),
        evidence_accuracy=_rate([r.evidence_ok for r in results]),
        tool_use_accuracy=_rate([r.tools_ok for r in results]),
        next_step_accuracy=_rate([r.steps_ok for r in results]),
        total_cost_usd=sum(r.cost_usd for r in results),
        mean_seconds=sum(seconds) / len(seconds) if seconds else 0.0,
        max_seconds=max(seconds, default=0.0),
    )


def format_investigation_summary(summary: InvestigationSummary) -> str:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0%}"

    return "\n".join(
        [
            "",
            f"Investigator model: {summary.model}",
            f"Cases: {summary.cases}  passed {summary.passed}  failed {summary.failed}"
            f"  errors {summary.errors}",
            f"Root cause accuracy (top 1): {pct(summary.root_cause_accuracy)}",
            f"Root cause in top 3:         {pct(summary.top3_accuracy)}",
            f"Evidence cited:              {pct(summary.evidence_accuracy)}",
            f"Right tools used:            {pct(summary.tool_use_accuracy)}",
            f"Useful next steps:           {pct(summary.next_step_accuracy)}",
            f"Cost: ${summary.total_cost_usd:.4f}   "
            f"Latency: mean {summary.mean_seconds:.1f}s, max {summary.max_seconds:.1f}s",
        ]
    )


def format_investigation_result(result: InvestigationResult) -> str:
    label = {"passed": "PASS", "failed": "FAIL", "error": "ERR "}[result.status]
    line = f"{label} {result.id:<28} {result.seconds:5.1f}s  ${result.cost_usd:.4f}"
    if result.status == "error":
        return f"{line}\n       {result.error}"
    return line + "".join(f"\n       - {f}" for f in result.failures)


def report_json(summary: InvestigationSummary, results: list[InvestigationResult]) -> str:
    return json.dumps(
        {"summary": summary.model_dump(), "results": [r.model_dump() for r in results]}, indent=2
    )
