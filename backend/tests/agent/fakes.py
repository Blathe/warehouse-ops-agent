"""A scripted stand-in for the Anthropic client, so agent tests never call the API."""

import copy
from typing import Any, cast

from anthropic import Anthropic
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage

ToolCall = tuple[str, str, dict[str, Any]]  # (tool_use id, tool name, input)


def text_reply(text: str, stop_reason: str = "end_turn") -> BetaMessage:
    return _message([BetaTextBlock.model_construct(type="text", text=text)], stop_reason)


def tool_reply(*calls: ToolCall, text: str = "") -> BetaMessage:
    blocks: list[Any] = [BetaTextBlock.model_construct(type="text", text=text)] if text else []
    blocks += [
        BetaToolUseBlock.model_construct(type="tool_use", id=id_, name=name, input=args)
        for id_, name, args in calls
    ]
    return _message(blocks, "tool_use")


def refusal() -> BetaMessage:
    return _message([], "refusal")


def _message(content: list[Any], stop_reason: str) -> BetaMessage:
    return BetaMessage.model_construct(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-opus-5-5",
        content=content,
        stop_reason=stop_reason,
        usage=BetaUsage.model_construct(input_tokens=10, output_tokens=10),
    )


class FakeMessages:
    def __init__(self, responses: list[BetaMessage]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> BetaMessage:
        # Copy, because the agent keeps appending to the same messages list.
        self.requests.append(copy.deepcopy(kwargs))
        if not self.responses:
            raise AssertionError("The agent made more model calls than the test scripted")
        return self.responses.pop(0)


class FakeBeta:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages


class FakeClient:
    def __init__(self, *responses: BetaMessage) -> None:
        self.messages = FakeMessages(list(responses))
        self.beta = FakeBeta(self.messages)

    def as_anthropic(self) -> Anthropic:
        return cast(Anthropic, self)
