import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from tests.conftest import make_memory_engine
from warehouse_ops.db.engine import readonly_session, reset_db
from warehouse_ops.db.models import Picker, Shift


def test_readonly_session_rejects_writes_and_resets_afterwards() -> None:
    engine = make_memory_engine()
    reset_db(engine)

    with readonly_session(engine) as session:
        assert session.exec(select(Picker)).all() == []  # reads work
        session.add(Picker(name="Test Picker", shift=Shift.FIRST))
        with pytest.raises(OperationalError, match="readonly"):
            session.flush()

    # The same pooled connection is writable again for normal sessions.
    with Session(engine) as session:
        session.add(Picker(name="Test Picker", shift=Shift.FIRST))
        session.commit()
        assert len(session.exec(select(Picker)).all()) == 1
