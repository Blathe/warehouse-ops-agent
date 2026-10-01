"""Shared pytest fixtures (pytest finds this file automatically)."""

from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from warehouse_ops.db.engine import get_engine
from warehouse_ops.db.seed import SeedSummary, seed_database

AS_OF = datetime(2026, 6, 1, 13, 0)  # a Monday afternoon in the spring peak


def make_memory_engine() -> Engine:
    # StaticPool keeps one connection, so the in-memory database survives between sessions.
    return get_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


@pytest.fixture(scope="session")
def seeded() -> tuple[Engine, SeedSummary]:
    """One seeded in-memory database shared by the whole test run (treat it as read-only)."""
    engine = make_memory_engine()
    return engine, seed_database(engine, seed=42, as_of=AS_OF)


@pytest.fixture
def session(seeded: tuple[Engine, SeedSummary]) -> Iterator[Session]:
    with Session(seeded[0]) as session:
        yield session
