"""Database engine setup.

The URL comes from ``DATABASE_URL`` (SQLite locally, Postgres when deployed) and
defaults to ``backend/warehouse.db``.
"""

import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlmodel import SQLModel, create_engine

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
