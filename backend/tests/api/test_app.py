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


def test_models_lists_the_choices_with_prices(engine: Engine) -> None:
    body = make_client(engine, FakeClient()).get("/api/models").json()
    assert body["default"] == "claude-opus-5-5"
    ids = [m["id"] for m in body["models"]]
    assert ids == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"]
    assert all(m["input_per_mtok"] > 0 and m["label"] for m in body["models"])


def test_chat_uses_the_requested_model(engine: Engine) -> None:
    fake = FakeClient(text_reply("Hi"))
    body = (
        make_client(engine, fake)
        .post("/api/chat", json={"message": "hi", "model": "claude-sonnet-5-5"})
        .json()
    )
    assert body["model"] == "claude-sonnet-5-5"
    assert fake.messages.requests[0]["model"] == "claude-sonnet-5-5"


def test_unknown_model_is_422(engine: Engine) -> None:
    response = make_client(engine, FakeClient()).post(
        "/api/chat", json={"message": "hi", "model": "nope"}
    )
    assert response.status_code == 422


def test_floor_map(engine: Engine) -> None:
    body = make_client(engine, FakeClient()).get("/api/floor-map").json()
    assert len(body["bays"]) == 400
    assert set(body["counts"]) == {"ok", "low", "empty", "unassigned"}
    first = body["bays"][0]
    assert first["pick"]["location"] == "A-01-01-1" and len(first["reserve"]) == 2


def test_tasks_default_to_the_active_ones(engine: Engine) -> None:
    api = make_client(engine, FakeClient())

    tasks = api.get("/api/tasks").json()

    assert tasks and {t["status"] for t in tasks} <= {"PROPOSED", "APPROVED"}
    assert {"task_id", "sku_code", "description", "from_location", "to_location", "qty"} <= set(
        tasks[0]
    )


def test_tasks_can_be_filtered_by_status(engine: Engine) -> None:
    api = make_client(engine, FakeClient())

    done = api.get("/api/tasks", params={"status": "done"}).json()
    everything = api.get("/api/tasks", params={"status": "all"}).json()

    assert done and {t["status"] for t in done} == {"DONE"}
    assert len(everything) > len(done)


def test_tasks_reject_an_unknown_filter(engine: Engine) -> None:
    api = make_client(engine, FakeClient())
    assert api.get("/api/tasks", params={"status": "bogus"}).status_code == 422


def test_a_task_approved_in_chat_shows_up_as_active(engine: Engine) -> None:
    fake = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", create_args(engine))),
        text_reply("Task created."),
    )
    api = make_client(engine, fake)
    before = len(api.get("/api/tasks").json())

    turn = api.post("/api/chat", json={"message": "Refill it"}).json()
    api.post(
        f"/api/conversations/{turn['conversation_id']}/approval",
        json={"approve": True, "decided_by": "Pat"},
    )

    tasks = api.get("/api/tasks").json()
    assert len(tasks) == before + 1
    assert tasks[0]["created_by"] == "agent" and tasks[0]["approved_by"] == "Pat"
