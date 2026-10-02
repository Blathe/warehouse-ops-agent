# Warehouse Ops Agent

Portfolio project: a Claude-powered agent that helps a warehouse supervisor handle
**short picks and replenishment**, through MCP tools over a realistic database for a fishing tackle and gear warehouse.
The product spec is [docs/spec.md](docs/spec.md); read it before changing the data model or tools.

The owner (Scott) comes from C#/.NET MVC + MySQL and is learning Python and React.
When introducing a Python or React idiom, explain it briefly, with a .NET comparison when one helps.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLModel (Pydantic + SQLAlchemy), SQLite locally, Postgres when deployed |
| Tools | MCP server (official `mcp` Python SDK v2, `MCPServer`; older docs call it FastMCP) exposing warehouse tools |
| Agent | Anthropic Python SDK, tool use over the same tool functions, human approval for writes |
| Tests / evals | pytest for unit + integration tests; an eval harness of 30–50 questions under `backend/evals/` |
| Front end | React + Vite + TypeScript + Tailwind + shadcn/ui; chat built on shadcn's MessageScroller; floor map view |
| Tooling | uv (packages, venv, lockfile), ruff (lint + format), mypy (types) |

## Layout

```
backend/
  pyproject.toml            # deps + tool config (uv)
  src/warehouse_ops/
    db/                     # SQLModel tables, engine, seed / fake-data generator
    services/               # plain functions with the business logic (queries, validation)
    mcp_server/             # MCP tool wrappers around services/
    agent/                  # Claude agent loop, approval flow, tool-call logging
    api/                    # FastAPI app for the front end
    evals/                  # eval runner, scoring, and ground-truth facts from the seeded DB
  tests/                    # pytest, mirrors src/ layout
  evals/                    # eval questions (cases.yaml); run reports land in evals/results/
frontend/                   # React app (added in the agent + chat UI phase)
docs/                       # spec, ADRs, write-up drafts
```

Business logic lives in `services/`. MCP tools, the agent, and the API are thin wrappers,
so each rule is written and tested once.

## Commands

Run from `backend/`. Always invoke uv as `python -m uv` (it is not on PATH on this machine).

```
python -m uv sync                     # create .venv and install deps from uv.lock
python -m uv run seed-db              # reset + fill backend/warehouse.db (--seed, --as-of, --db-url)
python -m uv run warehouse-mcp        # MCP server on stdio (see docs/claude-desktop.md)
python -m uv run warehouse-api        # FastAPI + agent on http://127.0.0.1:8000 (reads ../.env)
python -m uv run pytest               # tests
python -m uv run run-evals            # agent evals: calls the Claude API and costs money
                                      # (--model, --only id1,id2; reports go to evals/results/)
python -m uv run --no-sync pytest     # skip the re-sync if an old Claude Desktop config still runs
                                      # warehouse-mcp.exe (a locked exe makes the sync fail)
python -m uv run ruff check . && python -m uv run ruff format .
python -m uv run mypy src
python -m uv add <pkg>                # add a runtime dependency
python -m uv add --dev <pkg>          # add a dev-only dependency
python -m uv sync --no-install-project --inexact  # install new deps while the MCP server is running
```

Front end, from `frontend/` (details in `frontend/README.md`):

```
npm install && npm run dev            # http://localhost:5173, proxies /api to the backend on :8000
npm test && npm run lint && npm run typecheck
```

## Rules

- **Type hints on every function** (params and return). `mypy src` should pass.
- **Every feature ships with tests.** Services get unit tests against a seeded in-memory SQLite DB;
  tools get at least one test proving the wrapper calls the service correctly.
- **Small PRs**: one feature per branch/PR (e.g. "add pick_face table + seed", "add list_short_picks tool").
  Branch names: `feat/...`, `fix/...`, `chore/...`, `docs/...`.
- **Read-only by default**: query tools use a read-only DB session. The only write tool
  (`create_replenishment_task`) must go through human approval and validate inputs in `services/`.
- **Approval is human-only**: approving/rejecting a task (`decide_replenishment_task`) is never exposed
  as an MCP or agent tool, so a model can't approve its own proposal.
- **Finishing a task is simulator-only**: moving an APPROVED task to DONE (and the stock with it) happens
  only through `POST /api/simulation/tick` (`complete_next_replenishment_task`), never as an MCP or agent
  tool. `tests/agent/test_tools.py` fails if a tool that decides or completes tasks is added.
- **Log every tool call** (tool, args, result summary, duration, approval decision) to the `tool_call_log` table.
- **Seeded fake data is deterministic** (fixed random seed) so tests and evals are reproducible.
- **Secrets** come from `.env` (see `.env.example`); never commit keys.
- Add a dependency only in the PR that first uses it.
