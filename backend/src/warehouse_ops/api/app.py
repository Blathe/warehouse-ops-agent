"""HTTP API for the front end.

Run from backend/:  python -m uv run warehouse-api   (http://127.0.0.1:8000/docs)

Conversations live in memory for now, so they are lost on restart and the API
must run as a single process.
"""

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from random import Random
from threading import Lock
from typing import Literal

import anthropic
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session

from warehouse_ops import clock
from warehouse_ops.agent.investigator import Investigator
from warehouse_ops.agent.loop import Agent, AgentStateError, AgentTurn, Conversation
from warehouse_ops.agent.models import DEFAULT_MODEL, MODEL_OPTIONS, ModelOption, is_supported
from warehouse_ops.db.engine import BACKEND_DIR, get_engine, readonly_session
from warehouse_ops.db.models import CountStatus, ReplenishmentStatus
from warehouse_ops.services import cycle_counts, replenishment_tasks
from warehouse_ops.services.cycle_counts import CycleCountOut, CycleCountRun
from warehouse_ops.services.errors import NotFoundError, RuleViolationError
from warehouse_ops.services.floor_map import FloorMap, get_floor_map
from warehouse_ops.services.overview import Overview, get_overview
from warehouse_ops.services.replenishment import OPEN_REPLENISHMENT_STATUSES
from warehouse_ops.services.schemas import ReplenishmentTaskOut

# "active" = still to be done: waiting for approval, or approved and not finished.
TaskFilter = Literal["active", "done", "rejected", "all"]
TASK_FILTERS: dict[TaskFilter, tuple[ReplenishmentStatus, ...] | None] = {
    "active": OPEN_REPLENISHMENT_STATUSES,
    "done": (ReplenishmentStatus.DONE,),
    "rejected": (ReplenishmentStatus.REJECTED,),
    "all": None,
}


# "open" = needs a supervisor: a discrepancy, or one waiting for its recount.
CountFilter = Literal["open", "resolved", "all"]
COUNT_FILTERS: dict[CountFilter, tuple[CountStatus, ...]] = {
    "open": cycle_counts.OPEN_STATUSES,
    "resolved": (CountStatus.ACCEPTED, CountStatus.RECOUNTED),
    "all": tuple(CountStatus),
}


class AcceptCountRequest(BaseModel):
    decided_by: str = Field(min_length=1)
    reason: str = Field(min_length=1, description="Why the system should match the count")


class RecountRequest(BaseModel):
    decided_by: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None  # omit to start a new conversation
    model: str | None = None  # see GET /api/models; omit to keep the conversation's model


class ModelsResponse(BaseModel):
    default: str
    models: list[ModelOption]


class TickResponse(BaseModel):
    completed: ReplenishmentTaskOut | None  # None when no approved task was waiting


class ApprovalRequest(BaseModel):
    approve: bool
    decided_by: str = Field(min_length=1, description="Name of the person deciding")


def create_app(
    *,
    engine: Engine | None = None,
    client: anthropic.Anthropic | None = None,
    now: Callable[[], datetime] = clock.now,
    investigation_workers: int = 4,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build the app; tests pass an in-memory engine and a fake Claude client.

    ``static_dir`` is the built front end (``frontend/dist``). When given, the app serves it
    too, so one process (one container) is the whole product.
    """
    app = FastAPI(title="Warehouse Ops Agent")
    engine = engine or get_engine()
    client = client or anthropic.Anthropic()
    agent = Agent(client, engine, now)
    investigator = Investigator(client, engine, now, parallel=investigation_workers)
    conversations: dict[str, Conversation] = {}
    lock = Lock()  # one request at a time per process: conversations aren't thread-safe
    simulation_lock = Lock()  # so two overlapping ticks can't finish the same task twice

    def get_conversation(conversation_id: str) -> Conversation:
        conversation = conversations.get(conversation_id)
        if conversation is None:
            raise HTTPException(404, f"No conversation {conversation_id!r}")
        return conversation

    def run(step: Callable[[], AgentTurn]) -> AgentTurn:
        try:
            return step()
        except AgentStateError as exc:
            raise HTTPException(409, str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise HTTPException(
                502, f"Claude API error ({exc.status_code}): {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise HTTPException(502, "Could not reach the Claude API") from exc

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/floor-map")
    def floor_map() -> FloorMap:
        with readonly_session(engine) as session:
            return get_floor_map(session)

    @app.get("/api/overview")
    def overview() -> Overview:
        with readonly_session(engine) as session:
            return get_overview(session, now=now())

    @app.get("/api/tasks")
    def tasks(status: TaskFilter = "active") -> list[ReplenishmentTaskOut]:
        with readonly_session(engine) as session:
            return replenishment_tasks.list_replenishment_tasks(session, TASK_FILTERS[status])

    @app.post("/api/simulation/tick")
    def simulation_tick() -> TickResponse:
        """Simulated floor crew: finish the oldest approved task and move its stock.

        The front end calls this every few seconds while "Simulate crew" is on. It is not
        an agent tool, so the model can never complete a task itself.
        """
        with simulation_lock, Session(engine) as session:
            try:
                completed = replenishment_tasks.complete_next_replenishment_task(session, now())
            except RuleViolationError as exc:
                raise HTTPException(409, str(exc)) from exc
            session.commit()
            return TickResponse(completed=completed)

    @app.post("/api/simulation/cycle-count")
    def simulate_cycle_count(background: BackgroundTasks) -> CycleCountRun:
        """Simulated clerk: count ~30 locations, including every planted problem.

        Each discrepancy it opens is investigated by the AI in the background; the response
        already shows those investigations as RUNNING.
        """
        with simulation_lock, Session(engine) as session:
            result = cycle_counts.simulate_cycle_count(session, rng=Random(), now=now())
            ids = [investigator.start(session, d.id) for d in result.discrepancies]
            result.discrepancies = [
                cycle_counts.get_cycle_count(session, d.id) for d in result.discrepancies
            ]
            session.commit()
        background.add_task(investigator.run_many, ids)
        return result

    @app.post("/api/cycle-counts/{count_id}/investigate")
    def investigate(count_id: int, background: BackgroundTasks) -> CycleCountOut:
        """Run the AI investigation again (e.g. after a failure). Open discrepancies only."""
        with simulation_lock, Session(engine) as session:
            try:
                count = cycle_counts.get_cycle_count(session, count_id)
            except NotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc
            if count.status != CountStatus.DISCREPANCY:
                raise HTTPException(409, f"Count #{count_id} is not an open discrepancy")
            investigation_id = investigator.start(session, count_id)
            result = cycle_counts.get_cycle_count(session, count_id)
            session.commit()
        background.add_task(investigator.run, investigation_id)
        return result

    @app.get("/api/cycle-counts")
    def list_counts(status: CountFilter = "open") -> list[CycleCountOut]:
        """Counts newest first. Matched counts only show under "all"."""
        with readonly_session(engine) as session:
            return cycle_counts.list_cycle_counts(session, COUNT_FILTERS[status])

    @app.post("/api/cycle-counts/{count_id}/accept")
    def accept_count(count_id: int, request: AcceptCountRequest) -> CycleCountOut:
        """A supervisor accepts the count: the system is adjusted to it (never an agent tool)."""
        return resolve_count(
            lambda session: cycle_counts.accept_cycle_count(
                session,
                count_id=count_id,
                decided_by=request.decided_by,
                reason=request.reason,
                now=now(),
            )
        )

    @app.post("/api/cycle-counts/{count_id}/recount")
    def recount(count_id: int, request: RecountRequest) -> CycleCountOut:
        return resolve_count(
            lambda session: cycle_counts.request_recount(
                session, count_id=count_id, decided_by=request.decided_by, now=now()
            )
        )

    def resolve_count(step: Callable[[Session], CycleCountOut]) -> CycleCountOut:
        with simulation_lock, Session(engine) as session:
            try:
                result = step(session)
            except NotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc
            except RuleViolationError as exc:
                raise HTTPException(409, str(exc)) from exc
            session.commit()
            return result

    @app.get("/api/models")
    def models() -> ModelsResponse:
        return ModelsResponse(default=DEFAULT_MODEL, models=MODEL_OPTIONS)

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> AgentTurn:
        if request.model is not None and not is_supported(request.model):
            raise HTTPException(422, f"Unsupported model {request.model!r}")
        with lock:
            if request.conversation_id is None:
                conversation = Conversation()
                conversations[conversation.id] = conversation
            else:
                conversation = get_conversation(request.conversation_id)
            return run(lambda: agent.send(conversation, request.message, request.model))

    @app.post("/api/conversations/{conversation_id}/approval")
    def approval(conversation_id: str, request: ApprovalRequest) -> AgentTurn:
        with lock:
            conversation = get_conversation(conversation_id)
            return run(
                lambda: agent.resolve(
                    conversation, approve=request.approve, decided_by=request.decided_by
                )
            )

    if static_dir is not None:
        mount_front_end(app, static_dir)

    return app


def mount_front_end(app: FastAPI, static_dir: Path) -> None:
    """Serve the built React app, falling back to index.html so page URLs survive a refresh."""
    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def front_end(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")  # unknown API routes must not return HTML
        file = (root / path).resolve()
        if file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        return FileResponse(root / "index.html")


def main() -> None:
    load_dotenv(BACKEND_DIR.parent / ".env")  # ANTHROPIC_API_KEY, DATABASE_URL, WAREHOUSE_AS_OF
    # A container must bind 0.0.0.0 to be reachable; locally the default stays loopback-only.
    host = os.environ.get("WAREHOUSE_API_HOST", "127.0.0.1")
    static = os.environ.get("WAREHOUSE_STATIC_DIR")  # set in the Docker image
    uvicorn.run(create_app(static_dir=Path(static) if static else None), host=host, port=8000)
