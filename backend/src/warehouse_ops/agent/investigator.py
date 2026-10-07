"""The cycle count investigator: explains one discrepancy from the inventory data.

Every discrepancy a simulated count opens is investigated automatically, in the
background, on a lower-cost model. The investigator only has read-only tools and ends
by calling ``submit_findings``; it can't accept or recount anything (a person does).
"""

import json
import os
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import anthropic
from anthropic import Anthropic
from anthropic.types.beta import BetaMessageParam, BetaToolParam, BetaToolResultBlockParam
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import Engine
from sqlmodel import Session

from warehouse_ops import clock
from warehouse_ops.agent.execution import execute_tool_call
from warehouse_ops.agent.models import is_supported, request_options
from warehouse_ops.agent.tools import TOOLS, ToolContext
from warehouse_ops.db.engine import readonly_session
from warehouse_ops.db.models import Investigation, InvestigationStatus, LogSource
from warehouse_ops.services.cycle_counts import (
    Cause,
    InvestigationOut,
    get_cycle_count,
    investigation_out,
)
from warehouse_ops.tool_log import WAREHOUSE_CONTEXT, record_model_call

DEFAULT_INVESTIGATOR_MODEL = "claude-sonnet-5-5"
NO_KEY = "No Claude API key is set. Add ANTHROPIC_API_KEY to the .env file and restart the API."
KEY_REJECTED = "The Claude API key was rejected. Check ANTHROPIC_API_KEY in the .env file."
MAX_TOKENS = 8000
MAX_STEPS = 10
PARALLEL = 4  # investigations running at once after a count

TOOL_NAMES = (
    "get_inventory_history",
    "get_nearby_stock",
    "list_open_picks",
    "list_discrepancies",
    "find_stock",
)
INVESTIGATION_TOOLS = {name: TOOLS[name] for name in TOOL_NAMES}

SYSTEM_PROMPT = f"""\
You are an inventory control analyst. A cycle count at one location didn't match the
system. Work out what most likely happened, using only what the tools return.

{WAREHOUSE_CONTEXT}

How to investigate:
- Start with the ledger for the location and SKU (get_inventory_history): the changes
  behind the system qty, such as manual adjustments (note any with a blank reason),
  replenishments in or out, receipts and picks.
- Look at the neighbouring slots (get_nearby_stock) and the other open discrepancies
  (list_discrepancies). An opposite variance of the same size, or the same LPN somewhere
  else, usually means stock is in the wrong place or a move was recorded wrongly.
- Compare the counted qty with the SKU's case qty: units counted as cases look short by
  a factor of the case qty.
- At a pick face, check unconfirmed picks (list_open_picks): units already in a tote make
  a count look short.
- If a replenishment touched the location, check the other end of the move.
- If nothing in the data explains the variance, say so plainly. Never invent a cause
  the data doesn't support.

When you're done, call submit_findings once and nothing after it: a one or two sentence
summary, the likely causes ranked most likely first (usually one to three), each with a
likelihood and evidence quoting specific facts (dates, quantities, users, refs,
locations), and one to four concrete next steps (recount, check a named location, ask a
named person). Write for a shift supervisor: plain words, no jargon."""


class Findings(BaseModel):
    summary: str = Field(description="One or two sentences for the supervisor.")
    causes: list[Cause] = Field(description="Most likely first. Empty if nothing explains it.")
    next_steps: list[str] = Field(description="Concrete actions, most useful first.")


SUBMIT_TOOL: BetaToolParam = {
    "name": "submit_findings",
    "description": "Submit the finished investigation. Call this once, as the last step.",
    "input_schema": Findings.model_json_schema(),
}
TOOL_PARAMS = [spec.to_param() for spec in INVESTIGATION_TOOLS.values()] + [SUBMIT_TOOL]


def investigator_model() -> str:
    model = os.environ.get("INVESTIGATOR_MODEL", DEFAULT_INVESTIGATOR_MODEL)
    return model if is_supported(model) else DEFAULT_INVESTIGATOR_MODEL


class Investigator:
    def __init__(
        self,
        client: Anthropic,
        engine: Engine,
        now: Callable[[], datetime] = clock.now,
        model: str | None = None,
        parallel: int = PARALLEL,
    ) -> None:
        self._client = client
        self._engine = engine
        self._now = now
        self._model = model or investigator_model()
        self._parallel = parallel

    def start(self, session: Session, count_id: int) -> int:
        """Record a RUNNING investigation in the caller's transaction; returns its id."""
        row = Investigation(
            cycle_count_id=count_id,
            model=self._model,
            status=InvestigationStatus.RUNNING,
            started_at=self._now(),
        )
        session.add(row)
        session.flush()
        assert row.id is not None
        return row.id

    def run_many(self, investigation_ids: Iterable[int]) -> None:
        with ThreadPoolExecutor(max_workers=self._parallel) as pool:
            list(pool.map(self.run, investigation_ids))

    def run(self, investigation_id: int) -> InvestigationOut:
        """Investigate and store the result. Never raises: failures are recorded instead."""
        tool_calls = 0
        try:
            with readonly_session(self._engine) as session:
                row = session.get(Investigation, investigation_id)
                assert row is not None, f"No investigation #{investigation_id}"
                count = get_cycle_count(session, row.cycle_count_id)
            details = count.model_dump(mode="json", exclude={"investigation"})
            messages: list[BetaMessageParam] = [
                {
                    "role": "user",
                    "content": (
                        f"[Warehouse time: {self._now():%Y-%m-%d %H:%M}]\n"
                        "Investigate this cycle count discrepancy:\n"
                        f"{json.dumps(details, indent=2)}"
                    ),
                }
            ]
            session_id = f"investigation:{investigation_id}"
            for _ in range(MAX_STEPS):
                started = time.perf_counter()
                response = self._client.beta.messages.create(
                    model=self._model,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_PARAMS,
                    messages=messages,
                    **request_options(self._model),
                )
                model_call_id = record_model_call(
                    self._engine,
                    session_id=session_id,
                    source=LogSource.INVESTIGATOR,
                    model=self._model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    stop_reason=response.stop_reason,
                )
                if response.stop_reason == "refusal":
                    return self._finish(investigation_id, tool_calls, error="The model declined")
                messages.append({"role": "assistant", "content": response.content})
                calls = [b for b in response.content if b.type == "tool_use"]
                if not calls:
                    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
                    findings = Findings(summary=text or "No findings.", causes=[], next_steps=[])
                    return self._finish(investigation_id, tool_calls, findings=findings)

                results: list[BetaToolResultBlockParam] = []
                for call in calls:
                    if call.name == "submit_findings":
                        try:
                            findings = Findings.model_validate(call.input)
                        except ValidationError as exc:
                            results.append(_error(call.id, f"Invalid findings: {exc}"))
                            continue
                        return self._finish(investigation_id, tool_calls, findings=findings)
                    tool_calls += 1
                    block, _ = execute_tool_call(
                        self._engine,
                        INVESTIGATION_TOOLS,
                        call,
                        ToolContext(now=self._now()),
                        session_id=session_id,
                        source=LogSource.INVESTIGATOR,
                        model_call_id=model_call_id,
                    )
                    results.append(block)
                messages.append({"role": "user", "content": results})
            return self._finish(investigation_id, tool_calls, error="Ran out of steps")
        except anthropic.AuthenticationError:
            return self._finish(investigation_id, tool_calls, error=KEY_REJECTED)
        except anthropic.APIStatusError as exc:
            return self._finish(
                investigation_id, tool_calls, error=f"Claude API error ({exc.status_code})"
            )
        except anthropic.APIConnectionError:
            return self._finish(
                investigation_id, tool_calls, error="Could not reach the Claude API"
            )
        except Exception as exc:  # a background job must record its failure, not vanish
            message = NO_KEY if "authentication method" in str(exc) else str(exc)[:300]
            return self._finish(investigation_id, tool_calls, error=message)

    def _finish(
        self,
        investigation_id: int,
        tool_calls: int,
        *,
        findings: Findings | None = None,
        error: str | None = None,
    ) -> InvestigationOut:
        with Session(self._engine) as session:
            row = session.get(Investigation, investigation_id)
            assert row is not None
            row.tool_calls = tool_calls
            row.finished_at = self._now()
            if findings is not None:
                row.status = InvestigationStatus.DONE
                row.summary = findings.summary
                row.causes_json = json.dumps([c.model_dump() for c in findings.causes])
                row.next_steps_json = json.dumps(findings.next_steps)
            else:
                row.status = InvestigationStatus.FAILED
                row.error = error
            session.add(row)
            session.commit()
            return investigation_out(row)


def _error(tool_use_id: str, message: str) -> BetaToolResultBlockParam:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}
