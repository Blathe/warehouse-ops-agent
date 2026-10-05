"""The agent loop: send the conversation to Claude, run the tools it asks for, repeat.

Read tools run straight away. When Claude asks for a write tool, the loop stops and
returns ``needs_approval``; it continues only when ``resolve`` is called with a
person's decision. That pause can span HTTP requests, which is why this is a
hand-written loop rather than the SDK's tool runner.

The conversation history is append-only: each response's content goes back exactly
as Claude returned it (thinking blocks included).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from anthropic import Anthropic
from anthropic.types.beta import (
    BetaMessageParam,
    BetaToolResultBlockParam,
    BetaToolUseBlock,
)
from pydantic import BaseModel
from sqlalchemy import Engine

from warehouse_ops import clock
from warehouse_ops.agent.execution import ToolTrace, execute_tool_call
from warehouse_ops.agent.models import DEFAULT_MODEL, is_supported, request_options
from warehouse_ops.agent.tools import TOOLS, ToolContext
from warehouse_ops.db.models import Approval
from warehouse_ops.tool_log import WAREHOUSE_CONTEXT, record_tool_call

MAX_TOKENS = 16000
MAX_STEPS = 12  # model calls per user message, a guard against runaway loops

SYSTEM_PROMPT = f"""\
You help a shift supervisor at a warehouse deal with short picks and replenishment.

{WAREHOUSE_CONTEXT}

Answer from tool results only. If the data doesn't show something, say so rather than
guessing. Keep answers short and scannable: lead with the answer, use location codes and
quantities, and use a short list or table when there are several items.

Creating a replenishment task needs the supervisor's approval, which the app asks for
when you call create_replenishment_task. Only call it when the supervisor wants stock
moved; when they only ask what needs replenishing, list the suggested moves instead.
Use the suggested qty and source from list_replenishment_needs unless told otherwise.
Skip faces that already have an open task or have no reserve stock, and say why.

You can also look into cycle count discrepancies with list_discrepancies,
get_inventory_history, get_nearby_stock and list_open_picks. Most discrepancies already
have an AI investigation attached; build on it, and check the data yourself when asked
why a count is off. Accepting a count or asking for a recount is the supervisor's call
on the Cycle counts page; you can't do either, so point them there."""

TOOL_PARAMS = [spec.to_param() for spec in TOOLS.values()]


class AgentStateError(RuntimeError):
    """The request doesn't fit the conversation's state (e.g. approving with nothing pending)."""


class PendingAction(BaseModel):
    tool_use_id: str
    tool: str
    input: dict[str, Any]


class AgentTurn(BaseModel):
    conversation_id: str
    model: str
    status: Literal["done", "needs_approval"]
    reply: str
    pending: list[PendingAction] = []
    tool_calls: list[ToolTrace] = []


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: uuid4().hex)
    messages: list[BetaMessageParam] = field(default_factory=list)
    # While waiting for approval: the write calls, and results of reads from the same turn.
    pending_calls: list[BetaToolUseBlock] = field(default_factory=list)
    pending_results: list[BetaToolResultBlockParam] = field(default_factory=list)
    # Can change between messages. Thinking blocks from another model are simply
    # ignored by the API, so switching mid-conversation is safe.
    model: str = DEFAULT_MODEL


class Agent:
    def __init__(
        self,
        client: Anthropic,
        engine: Engine,
        now: Callable[[], datetime] = clock.now,
    ) -> None:
        self._client = client
        self._engine = engine
        self._now = now

    def send(self, conversation: Conversation, text: str, model: str | None = None) -> AgentTurn:
        """Add a user message and run until Claude answers or asks to write.

        ``model`` switches the conversation to another supported model from here on.
        """
        if conversation.pending_calls:
            raise AgentStateError("Approve or reject the pending action first")
        if model is not None:
            if not is_supported(model):
                raise ValueError(f"Unsupported model {model!r}")
            conversation.model = model
        conversation.messages.append(
            {"role": "user", "content": f"[Warehouse time: {self._now():%Y-%m-%d %H:%M}]\n{text}"}
        )
        return self._run(conversation, [])

    def resolve(self, conversation: Conversation, *, approve: bool, decided_by: str) -> AgentTurn:
        """Apply a person's decision on the pending write(s) and let Claude continue."""
        if not conversation.pending_calls:
            raise AgentStateError("Nothing is waiting for approval")
        traces: list[ToolTrace] = []
        results = list(conversation.pending_results)
        for call in conversation.pending_calls:
            if approve:
                ctx = ToolContext(now=self._now(), approved_by=decided_by)
                results.append(self._execute(conversation, call, ctx, traces, Approval.APPROVED))
            else:
                results.append(self._reject(conversation, call, decided_by, traces))
        conversation.pending_calls = []
        conversation.pending_results = []
        conversation.messages.append({"role": "user", "content": results})
        return self._run(conversation, traces)

    def _run(self, conversation: Conversation, traces: list[ToolTrace]) -> AgentTurn:
        for _ in range(MAX_STEPS):
            response = self._client.beta.messages.create(
                model=conversation.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOL_PARAMS,
                messages=conversation.messages,
                **request_options(conversation.model),
            )
            text = "\n".join(b.text for b in response.content if b.type == "text").strip()

            if response.stop_reason == "refusal":
                # Nothing usable to keep; leave the history ending on the user's message.
                return self._turn(conversation, "done", "I can't help with that request.", traces)

            conversation.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                if response.stop_reason == "max_tokens":
                    text += "\n\n(The answer was cut off because it got too long.)"
                return self._turn(conversation, "done", text, traces)

            calls = [b for b in response.content if b.type == "tool_use"]
            results = []
            writes = []
            for call in calls:
                spec = TOOLS.get(call.name)
                if spec is not None and spec.writes:
                    writes.append(call)
                else:
                    ctx = ToolContext(now=self._now())
                    results.append(self._execute(conversation, call, ctx, traces))

            if writes:
                conversation.pending_calls = writes
                conversation.pending_results = results
                pending = [
                    PendingAction(tool_use_id=c.id, tool=c.name, input=dict(c.input))
                    for c in writes
                ]
                turn = self._turn(conversation, "needs_approval", text, traces)
                turn.pending = pending
                return turn

            # All results from one response go back together in a single user message.
            conversation.messages.append({"role": "user", "content": results})

        return self._turn(
            conversation, "done", "I stopped because this took too many steps.", traces
        )

    def _execute(
        self,
        conversation: Conversation,
        call: BetaToolUseBlock,
        ctx: ToolContext,
        traces: list[ToolTrace],
        approval: Approval = Approval.NOT_APPLICABLE,
    ) -> BetaToolResultBlockParam:
        block, trace = execute_tool_call(
            self._engine, TOOLS, call, ctx, session_id=conversation.id, approval=approval
        )
        traces.append(trace)
        return block

    def _reject(
        self,
        conversation: Conversation,
        call: BetaToolUseBlock,
        decided_by: str,
        traces: list[ToolTrace],
    ) -> BetaToolResultBlockParam:
        summary = f"rejected by {decided_by}"
        args = dict(call.input)
        record_tool_call(
            self._engine,
            ts=self._now(),
            session_id=conversation.id,
            tool=call.name,
            args=args,
            summary=summary,
            duration_ms=0,
            approval=Approval.REJECTED,
        )
        traces.append(
            ToolTrace(
                tool=call.name, input=args, ok=False, summary=summary, approval=Approval.REJECTED
            )
        )
        return {
            "type": "tool_result",
            "tool_use_id": call.id,
            "content": f"{decided_by} rejected this action, so nothing was created.",
        }

    @staticmethod
    def _turn(
        conversation: Conversation,
        status: Literal["done", "needs_approval"],
        reply: str,
        traces: list[ToolTrace],
    ) -> AgentTurn:
        return AgentTurn(
            conversation_id=conversation.id,
            model=conversation.model,
            status=status,
            reply=reply,
            tool_calls=traces,
        )
