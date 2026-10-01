import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.agent.fakes import FakeClient, text_reply, tool_reply
from tests.agent.test_loop import create_args
from tests.conftest import AS_OF, make_memory_engine
from warehouse_ops.api.app import create_app
from warehouse_ops.db.seed import seed_database


@pytest.fixture
def engine() -> Engine:
    engine = make_memory_engine()
    seed_database(engine, seed=42, as_of=AS_OF)
    return engine


def make_client(engine: Engine, fake: FakeClient) -> TestClient:
    return TestClient(create_app(engine=engine, client=fake.as_anthropic(), now=lambda: AS_OF))


def test_health(engine: Engine) -> None:
    assert make_client(engine, FakeClient()).get("/api/health").json() == {"status": "ok"}


def test_chat_then_approve(engine: Engine) -> None:
    fake = FakeClient(
        text_reply("13 faces need stock."),
        tool_reply(("tu_1", "create_replenishment_task", create_args(engine))),
        text_reply("Task created."),
    )
    api = make_client(engine, fake)

    first = api.post("/api/chat", json={"message": "What needs replenishing?"}).json()
    assert first["status"] == "done" and first["reply"] == "13 faces need stock."
    conversation_id = first["conversation_id"]

    second = api.post(
        "/api/chat", json={"message": "Refill the first one", "conversation_id": conversation_id}
    ).json()
    assert second["status"] == "needs_approval"
    assert second["pending"][0]["tool"] == "create_replenishment_task"

    third = api.post(
        f"/api/conversations/{conversation_id}/approval",
        json={"approve": True, "decided_by": "Pat"},
    ).json()
    assert third["status"] == "done" and third["reply"] == "Task created."
    assert third["tool_calls"][0]["approval"] == "approved"


def test_unknown_conversation_is_404(engine: Engine) -> None:
    api = make_client(engine, FakeClient())
    response = api.post("/api/chat", json={"message": "hi", "conversation_id": "nope"})
    assert response.status_code == 404


def test_approval_with_nothing_pending_is_409(engine: Engine) -> None:
    api = make_client(engine, FakeClient(text_reply("Hi")))
    conversation_id = api.post("/api/chat", json={"message": "hi"}).json()["conversation_id"]
    response = api.post(
        f"/api/conversations/{conversation_id}/approval",
        json={"approve": True, "decided_by": "Pat"},
    )
    assert response.status_code == 409


def test_empty_message_is_rejected(engine: Engine) -> None:
    api = make_client(engine, FakeClient())
    assert api.post("/api/chat", json={"message": ""}).status_code == 422


def test_claude_api_failure_is_502(engine: Engine) -> None:
    fake = FakeClient()

    def fail(**_: object) -> None:
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://example.test"))

    fake.messages.create = fail  # type: ignore[method-assign,assignment]
    response = make_client(engine, fake).post("/api/chat", json={"message": "hi"})
    assert response.status_code == 502
