"""Shared by both eval suites: the fixed "now", a seeded database, and usage metering."""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from anthropic import Anthropic
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool

from warehouse_ops.agent.models import MODEL_OPTIONS
from warehouse_ops.db.engine import BACKEND_DIR, get_engine
from warehouse_ops.db.seed import seed_database

AS_OF = datetime(2026, 6, 1, 13, 0)  # "now" for the seeded data and the models
SEED = 42
RESULTS_DIR = BACKEND_DIR / "evals" / "results"


def seeded_engine() -> Engine:
    # StaticPool keeps one connection, so the in-memory database survives between sessions.
    engine = get_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    seed_database(engine, seed=SEED, as_of=AS_OF)
    return engine


@dataclass
class Meter:
    """Token usage and model time for one case (cache tokens are not counted)."""

    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    seconds: float = 0.0


class _MeteredMessages:
    def __init__(self, inner: Any, meter: Meter) -> None:
        self._inner = inner
        self._meter = meter

    def create(self, **kwargs: Any) -> Any:
        started = time.perf_counter()
        response = self._inner.create(**kwargs)
        self._meter.seconds += time.perf_counter() - started
        self._meter.model_calls += 1
        self._meter.input_tokens += response.usage.input_tokens
        self._meter.output_tokens += response.usage.output_tokens
        return response


class _MeteredBeta:
    def __init__(self, messages: _MeteredMessages) -> None:
        self.messages = messages


class MeteredClient:
    """Stands in for ``Anthropic`` and records the usage of every ``beta.messages.create``."""

    def __init__(self, client: Anthropic, meter: Meter) -> None:
        self.beta = _MeteredBeta(_MeteredMessages(client.beta.messages, meter))

    def as_anthropic(self) -> Anthropic:
        return cast(Anthropic, self)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    option = next(m for m in MODEL_OPTIONS if m.id == model)
    return (input_tokens * option.input_per_mtok + output_tokens * option.output_per_mtok) / 1e6
