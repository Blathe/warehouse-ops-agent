from pathlib import Path

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
    # One investigation at a time: the in-memory test database is a single shared connection.
    app = create_app(
        engine=engine, client=fake.as_anthropic(), now=lambda: AS_OF, investigation_workers=1
    )
    return TestClient(app)


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


def drain(api: TestClient) -> None:
    while api.post("/api/simulation/tick").json()["completed"] is not None:
        pass


def test_tick_completes_the_oldest_approved_task(engine: Engine) -> None:
    api = make_client(engine, FakeClient())
    waiting = api.get("/api/tasks").json()
    expected = min(
        (t for t in waiting if t["status"] == "APPROVED"),
        key=lambda t: (t["decided_at"], t["task_id"]),
    )

    done = api.post("/api/simulation/tick").json()["completed"]

    assert done["task_id"] == expected["task_id"] and done["status"] == "DONE"
    assert len(api.get("/api/tasks").json()) == len(waiting) - 1
    assert expected["task_id"] in [t["task_id"] for t in api.get("/api/tasks?status=done").json()]


def test_tick_moves_stock_on_the_floor_map(engine: Engine) -> None:
    api = make_client(engine, FakeClient())

    def on_hand(location: str) -> int:
        bays = api.get("/api/floor-map").json()["bays"]
        return int(next(b["pick"]["on_hand"] for b in bays if b["pick"]["location"] == location))

    before = {t["task_id"]: on_hand(t["to_location"]) for t in api.get("/api/tasks").json()}
    done = api.post("/api/simulation/tick").json()["completed"]

    assert on_hand(done["to_location"]) == before[done["task_id"]] + done["qty"]


def test_tick_with_nothing_approved_returns_null(engine: Engine) -> None:
    api = make_client(engine, FakeClient())
    drain(api)

    assert api.post("/api/simulation/tick").json() == {"completed": None}
    assert api.get("/api/tasks").json() == []


def test_a_task_approved_in_chat_is_finished_by_a_tick(engine: Engine) -> None:
    fake = FakeClient(
        tool_reply(("tu_1", "create_replenishment_task", create_args(engine))),
        text_reply("Task created."),
    )
    api = make_client(engine, fake)
    drain(api)  # clear the seeded tasks so the next tick is for ours

    turn = api.post("/api/chat", json={"message": "Refill it"}).json()
    api.post(
        f"/api/conversations/{turn['conversation_id']}/approval",
        json={"approve": True, "decided_by": "Pat"},
    )
    done = api.post("/api/simulation/tick").json()["completed"]

    assert done["created_by"] == "agent" and done["approved_by"] == "Pat"
    assert done["status"] == "DONE"


def test_cycle_count_round_trip(engine: Engine) -> None:
    api = make_client(engine, FakeClient())

    run = api.post("/api/simulation/cycle-count").json()
    assert run["counted"] == 30 and len(run["discrepancies"]) == 8

    open_counts = api.get("/api/cycle-counts").json()
    assert {c["id"] for c in open_counts} == {d["id"] for d in run["discrepancies"]}
    # Pick-face counts (no LPN), so accepting can't clash with a pallet still recorded elsewhere.
    first, second = [c["id"] for c in open_counts if c["lpn"] is None][:2]

    missing_reason = api.post(f"/api/cycle-counts/{first}/accept", json={"decided_by": "Pat"})
    assert missing_reason.status_code == 422

    recount = api.post(f"/api/cycle-counts/{first}/recount", json={"decided_by": "Pat"})
    assert recount.json()["status"] == "RECOUNT_REQUESTED"
    assert (
        api.post(f"/api/cycle-counts/{first}/recount", json={"decided_by": "Pat"}).status_code
        == 409
    )
    assert (
        api.post("/api/cycle-counts/999999/recount", json={"decided_by": "Pat"}).status_code == 404
    )

    accepted = api.post(
        f"/api/cycle-counts/{second}/accept", json={"decided_by": "Pat", "reason": "Checked"}
    ).json()
    assert accepted["status"] == "ACCEPTED" and accepted["resolution_reason"] == "Checked"
    resolved = api.get("/api/cycle-counts", params={"status": "resolved"}).json()
    assert [c["id"] for c in resolved] == [second]


def test_a_cycle_count_starts_investigations_in_the_background(engine: Engine) -> None:
    findings = {"summary": "Explained.", "causes": [], "next_steps": ["Recount"]}
    replies = [tool_reply((f"tu_{i}", "submit_findings", findings)) for i in range(8)]
    api = make_client(engine, FakeClient(*replies))

    run = api.post("/api/simulation/cycle-count").json()

    assert all(d["investigation"]["status"] == "RUNNING" for d in run["discrepancies"])
    # TestClient runs background tasks before returning, so they're finished now.
    counts = api.get("/api/cycle-counts").json()
    assert [c["investigation"]["status"] for c in counts] == ["DONE"] * 8
    assert counts[0]["investigation"]["summary"] == "Explained."


def test_investigate_again(engine: Engine) -> None:
    api = make_client(engine, FakeClient())  # no replies scripted: investigations fail
    run = api.post("/api/simulation/cycle-count").json()
    count_id = run["discrepancies"][0]["id"]
    assert api.get("/api/cycle-counts").json()[0]["investigation"]["status"] == "FAILED"

    again = api.post(f"/api/cycle-counts/{count_id}/investigate")
    assert again.status_code == 200 and again.json()["investigation"]["status"] == "RUNNING"
    assert api.post("/api/cycle-counts/999999/investigate").status_code == 404


def test_serves_front_end_with_spa_fallback(engine: Engine, tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    app = create_app(
        engine=engine, client=FakeClient().as_anthropic(), now=lambda: AS_OF, static_dir=tmp_path
    )
    web = TestClient(app)

    assert web.get("/assets/app.js").text == "console.log(1)"
    assert web.get("/cycle-counts").text == "<div id=root></div>"  # client-side route
    assert web.get("/../../etc/passwd").text == "<div id=root></div>"  # no escaping the folder
    assert web.get("/api/health").json() == {"status": "ok"}  # API routes win
    assert web.get("/api/nope").status_code == 404  # and unknown ones aren't index.html
