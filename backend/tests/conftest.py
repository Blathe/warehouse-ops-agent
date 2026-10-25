"""Shared pytest fixtures (pytest finds this file automatically)."""

from collections.abc import Iterator
from datetime import datetime
from functools import cache

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


@cache
def _seeded_template() -> Engine:
    engine = make_memory_engine()
    seed_database(engine, seed=42, as_of=AS_OF)
    return engine


def fresh_seeded_engine() -> Engine:
    """A private copy of the seed-42 database, for tests that write to it.

    Seeding takes about a second; copying the seeded template with SQLite's backup API takes
    milliseconds, so each writing test still gets its own database without paying for a re-seed.
    """
    engine = make_memory_engine()
    with _seeded_template().connect() as source, engine.connect() as target:
        source.connection.driver_connection.backup(target.connection.driver_connection)  # type: ignore[union-attr]
    return engine


@pytest.fixture(scope="session")
def seeded() -> tuple[Engine, SeedSummary]:
    """One seeded in-memory database shared by the whole test run (treat it as read-only)."""
    engine = make_memory_engine()
    return engine, seed_database(engine, seed=42, as_of=AS_OF)


@pytest.fixture
def session(seeded: tuple[Engine, SeedSummary]) -> Iterator[Session]:
    with Session(seeded[0]) as session:
        yield session
