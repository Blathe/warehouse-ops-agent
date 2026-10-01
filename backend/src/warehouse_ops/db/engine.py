"""Database engine setup.

The URL comes from ``DATABASE_URL`` (SQLite locally, Postgres when deployed) and
defaults to ``backend/warehouse.db``.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

from warehouse_ops.db import models  # noqa: F401  (registers the tables on SQLModel.metadata)

BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = f"sqlite:///{BACKEND_DIR / 'warehouse.db'}"


def get_engine(url: str | None = None, **kwargs: Any) -> Engine:
    """Create an engine; SQLite connections get foreign key enforcement turned on."""
    engine = create_engine(url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), **kwargs)
    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless asked, per connection.
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def reset_db(engine: Engine) -> None:
    """Drop and recreate every table."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


_READONLY_SQL = {
    # dialect: (turn read-only on, turn it back off)
    "sqlite": ("PRAGMA query_only = ON", "PRAGMA query_only = OFF"),
    "postgresql": (
        "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY",
        "SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE",
    ),
}


@contextmanager
def readonly_session(engine: Engine) -> Iterator[Session]:
    """A session the database itself refuses to write through.

    Query tools use this, so even a buggy query can't change data.
    """
    on, off = _READONLY_SQL[engine.dialect.name]
    with engine.connect() as connection:
        connection.exec_driver_sql(on)
        try:
            with Session(bind=connection) as session:
                yield session
        finally:
            # The connection goes back to the pool afterwards, so undo the setting.
            connection.rollback()
            connection.exec_driver_sql(off)
