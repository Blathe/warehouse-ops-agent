"""Run the eval cases against the real agent and report how it did.

Run from backend/:  python -m uv run run-evals [--model claude-sonnet-5-5] [--only id1,id2]

This calls the Claude API (so it costs money and needs ANTHROPIC_API_KEY). Every case runs
against the same deterministic seeded database; the cost and latency of each case come from
the token usage and timing of its model calls.
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session, select

from warehouse_ops.agent.loop import Agent, AgentTurn, Conversation
from warehouse_ops.agent.models import DEFAULT_MODEL, MODEL_OPTIONS, is_supported
from warehouse_ops.agent.pricing import cost_usd
from warehouse_ops.db.engine import BACKEND_DIR
from warehouse_ops.db.models import ReplenishmentTask
from warehouse_ops.evals.cases import DEFAULT_CASES_PATH, EvalCase, Facts, load_cases, resolve
from warehouse_ops.evals.common import (
    AS_OF,
    RESULTS_DIR,
    Meter,
    MeteredClient,
    seeded_engine,
)
from warehouse_ops.evals.scoring import CaseScore, Observed, ObservedCall, score_case
from warehouse_ops.evals.truth import build_facts

APPROVER = "eval-runner"
MAX_APPROVALS = 3  # per case, a guard against an agent that keeps proposing writes


class CaseResult(BaseModel):
    id: str
    question: str
    status: str  # "passed", "failed", or "error" (the model call itself failed)
    tool_ok: bool | None = None
    args_ok: bool | None = None
    answer_ok: bool | None = None
    outcome_ok: bool | None = None
    failures: list[str] = []
    answer: str = ""
    calls: list[dict[str, Any]] = []
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    error: str | None = None


class Summary(BaseModel):
    model: str
    cases: int
    passed: int
    failed: int
    errors: int
    tool_selection_accuracy: float | None
    argument_accuracy: float | None
    answer_accuracy: float | None
    outcome_accuracy: float | None
    total_cost_usd: float
    mean_seconds: float
    max_seconds: float


def _agent_made_task(engine: Engine) -> bool:
    with Session(engine) as session:
        return (
            session.exec(
                select(ReplenishmentTask).where(ReplenishmentTask.created_by == "agent")
            ).first()
            is not None
        )


def run_case(case: EvalCase, *, client: Anthropic, engine: Engine, model: str) -> CaseResult:
    meter = Meter()
    agent = Agent(MeteredClient(client, meter).as_anthropic(), engine, now=lambda: AS_OF)
    conversation = Conversation()

    calls: list[ObservedCall] = []
    answers: list[str] = []
    try:
        turn: AgentTurn = agent.send(conversation, case.question, model=model)
        approvals = 0
        while True:
            calls += [ObservedCall(t.tool, t.input) for t in turn.tool_calls]
            calls += [ObservedCall(p.tool, p.input) for p in turn.pending]
            if turn.reply:
                answers.append(turn.reply)
            if turn.status != "needs_approval" or not case.approve_writes:
                break
            if approvals >= MAX_APPROVALS:
                break
            turn = agent.resolve(conversation, approve=True, decided_by=APPROVER)
            approvals += 1
    except anthropic.APIError as exc:
        return CaseResult(
            id=case.id,
            question=case.question,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            input_tokens=meter.input_tokens,
            output_tokens=meter.output_tokens,
            seconds=meter.seconds,
        )

    observed = Observed(calls, "\n".join(answers), _agent_made_task(engine))
    score: CaseScore = score_case(case, observed)
    return CaseResult(
        id=case.id,
        question=case.question,
        status="passed" if score.passed else "failed",
        tool_ok=score.tool_ok,
        args_ok=score.args_ok,
        answer_ok=score.answer_ok,
        outcome_ok=score.outcome_ok,
        failures=score.failures,
        answer=observed.answer,
        calls=[{"tool": c.tool, "args": c.args} for c in calls],
        input_tokens=meter.input_tokens,
        output_tokens=meter.output_tokens,
        cost_usd=cost_usd(model, meter.input_tokens, meter.output_tokens),
        seconds=meter.seconds,
    )


def _rate(checks: list[bool | None]) -> float | None:
    made = [c for c in checks if c is not None]
    return sum(made) / len(made) if made else None


def summarize(model: str, results: list[CaseResult]) -> Summary:
    seconds = [r.seconds for r in results]
    return Summary(
        model=model,
        cases=len(results),
        passed=sum(r.status == "passed" for r in results),
        failed=sum(r.status == "failed" for r in results),
        errors=sum(r.status == "error" for r in results),
        tool_selection_accuracy=_rate([r.tool_ok for r in results]),
        argument_accuracy=_rate([r.args_ok for r in results]),
        answer_accuracy=_rate([r.answer_ok for r in results]),
        outcome_accuracy=_rate([r.outcome_ok for r in results]),
        total_cost_usd=sum(r.cost_usd for r in results),
        mean_seconds=sum(seconds) / len(seconds) if seconds else 0.0,
        max_seconds=max(seconds, default=0.0),
    )


def run_evals(
    cases: list[EvalCase],
    *,
    client: Anthropic,
    model: str,
    on_result: Callable[[CaseResult], None] | None = None,
) -> list[CaseResult]:
    """Run every case in order. The database is reseeded after any case that writes."""
    engine = seeded_engine()
    with Session(engine) as session:
        facts: Facts = build_facts(session, AS_OF)

    results = []
    dirty = False
    for case in cases:
        if dirty:
            engine, dirty = seeded_engine(), False
        result = run_case(resolve(case, facts), client=client, engine=engine, model=model)
        dirty = case.approve_writes
        results.append(result)
        if on_result:
            on_result(result)
    return results


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _mark(check: bool | None) -> str:
    return "-" if check is None else ("ok" if check else "NO")


def format_result(result: CaseResult) -> str:
    label = {"passed": "PASS", "failed": "FAIL", "error": "ERR "}[result.status]
    line = f"{label} {result.id:<28} {result.seconds:5.1f}s  ${result.cost_usd:.4f}"
    if result.status == "error":
        return f"{line}\n       {result.error}"
    if result.failures:
        line += "".join(f"\n       - {f}" for f in result.failures)
    return line


def format_summary(summary: Summary) -> str:
    return "\n".join(
        [
            "",
            f"Model: {summary.model}",
            f"Cases: {summary.cases}  passed {summary.passed}  failed {summary.failed}"
            f"  errors {summary.errors}",
            f"Tool selection accuracy: {_pct(summary.tool_selection_accuracy)}",
            f"Argument accuracy:       {_pct(summary.argument_accuracy)}",
            f"Answer accuracy:         {_pct(summary.answer_accuracy)}",
            f"Outcome accuracy:        {_pct(summary.outcome_accuracy)}",
            f"Cost: ${summary.total_cost_usd:.4f}   "
            f"Latency: mean {summary.mean_seconds:.1f}s, max {summary.max_seconds:.1f}s",
        ]
    )


def save_report(summary: Summary, results: list[CaseResult]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"{stamp}-{summary.model}.json"
    report = {"summary": summary.model_dump(), "results": [r.model_dump() for r in results]}
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the agent evals (calls the Claude API).")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"one of {[m.id for m in MODEL_OPTIONS]}"
    )
    parser.add_argument(
        "--suite",
        choices=["agent", "investigator"],
        default="agent",
        help="agent: the chat agent's cases; investigator: the cycle count investigator's",
    )
    parser.add_argument("--cases", type=Path, default=None, help="defaults to the suite's YAML")
    parser.add_argument(
        "--rescore",
        type=Path,
        default=None,
        help="investigator suite: grade a saved report again with the current cases (no API calls)",
    )
    parser.add_argument("--only", default=None, help="comma-separated case ids to run")
    args = parser.parse_args()

    if not is_supported(args.model):
        sys.exit(f"Unsupported model {args.model!r}")
    load_dotenv(BACKEND_DIR.parent / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY") and not args.rescore:
        sys.exit("Set ANTHROPIC_API_KEY (in .env or the environment) to run the evals.")

    if args.suite == "investigator":
        sys.exit(_main_investigator(args))

    cases = load_cases(args.cases or DEFAULT_CASES_PATH)
    if args.only:
        wanted = set(args.only.split(","))
        unknown = wanted - {c.id for c in cases}
        if unknown:
            sys.exit(f"Unknown case ids: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.id in wanted]

    print(f"Running {len(cases)} cases on {args.model}...\n")
    results = run_evals(
        cases,
        client=anthropic.Anthropic(),
        model=args.model,
        on_result=lambda r: print(format_result(r), flush=True),
    )
    summary = summarize(args.model, results)
    print(format_summary(summary))
    print(f"\nReport saved to {save_report(summary, results)}")
    sys.exit(0 if summary.passed == summary.cases else 1)


def _main_investigator(args: argparse.Namespace) -> int:
    from warehouse_ops.evals import investigations as inv

    cases = inv.load_investigation_cases(args.cases or inv.DEFAULT_CASES_PATH)
    if args.rescore:
        report = json.loads(args.rescore.read_text(encoding="utf-8"))
        summary, results = inv.rescore_report(report, cases)
        for result in results:
            print(inv.format_investigation_result(result))
        print(inv.format_investigation_summary(summary))
        return 0 if summary.passed == summary.cases else 1
    if args.only:
        wanted = set(args.only.split(","))
        unknown = wanted - {c.id for c in cases}
        if unknown:
            sys.exit(f"Unknown case ids: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.id in wanted]

    print(f"Running {len(cases)} investigator cases on {args.model}...\n")
    results = inv.run_investigation_evals(
        cases,
        client=anthropic.Anthropic(),
        model=args.model,
        on_result=lambda r: print(inv.format_investigation_result(r), flush=True),
    )
    summary = inv.summarize_investigations(args.model, results)
    print(inv.format_investigation_summary(summary))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"{stamp}-investigator-{args.model}.json"
    path.write_text(inv.report_json(summary, results), encoding="utf-8")
    print(f"\nReport saved to {path}")
    return 0 if summary.passed == summary.cases else 1
