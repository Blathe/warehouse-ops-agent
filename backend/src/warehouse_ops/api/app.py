"""HTTP API for the front end.

Run from backend/:  python -m uv run warehouse-api   (http://127.0.0.1:8000/docs)

Conversations live in memory for now, so they are lost on restart and the API
must run as a single process.
"""

from collections.abc import Callable
from datetime import datetime
from threading import Lock

import anthropic
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from warehouse_ops import clock
from warehouse_ops.agent.loop import Agent, AgentStateError, AgentTurn, Conversation
from warehouse_ops.db.engine import BACKEND_DIR, get_engine


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None  # omit to start a new conversation


class ApprovalRequest(BaseModel):
    approve: bool
    decided_by: str = Field(min_length=1, description="Name of the person deciding")


def create_app(
    *,
    engine: Engine | None = None,
    client: anthropic.Anthropic | None = None,
    now: Callable[[], datetime] = clock.now,
) -> FastAPI:
    """Build the app; tests pass an in-memory engine and a fake Claude client."""
    app = FastAPI(title="Warehouse Ops Agent")
    agent = Agent(client or anthropic.Anthropic(), engine or get_engine(), now)
    conversations: dict[str, Conversation] = {}
    lock = Lock()  # one request at a time per process: conversations aren't thread-safe

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

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> AgentTurn:
        with lock:
            if request.conversation_id is None:
                conversation = Conversation()
                conversations[conversation.id] = conversation
            else:
                conversation = get_conversation(request.conversation_id)
            return run(lambda: agent.send(conversation, request.message))

    @app.post("/api/conversations/{conversation_id}/approval")
    def approval(conversation_id: str, request: ApprovalRequest) -> AgentTurn:
        with lock:
            conversation = get_conversation(conversation_id)
            return run(
                lambda: agent.resolve(
                    conversation, approve=request.approve, decided_by=request.decided_by
                )
            )

    return app


def main() -> None:
    load_dotenv(BACKEND_DIR.parent / ".env")  # ANTHROPIC_API_KEY, DATABASE_URL, WAREHOUSE_AS_OF
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
