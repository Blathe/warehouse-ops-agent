# Warehouse Ops Agent

A Claude-powered agent that helps a warehouse shift supervisor deal with **short picks and replenishment**, in plain English, over a realistic database for a fishing tackle distribution center.

> "Any short picks in zone A since 6am?" → the agent queries live data, explains what happened, and proposes a replenishment move. A human approves it. The model never approves its own work.

<!-- TODO: add a screenshot or GIF of the chat + floor map here (docs/demo.gif) -->

## The problem

A picker goes to a pick face and finds fewer units than the task expects: a **short pick**. Usually the stock is sitting on a pallet in reserve, and the pick face just wasn't refilled in time. Supervisors find out late and piece the picture together from several screens.

This agent lets a supervisor ask what's short, find where the stock is, and queue the fix from one chat.

## What it does

- **Answers from data, not guesses.** Four tools query the warehouse database (short picks, stock by SKU, pick faces needing replenishment, and a write tool to create replenishment tasks). The agent is instructed to say so when data is missing.
- **Human-only approval for writes.** The agent can only *propose* a replenishment task. When it does, the loop pauses and the UI shows an approval card. Approving or rejecting is exposed to the UI/API only, never as an agent or MCP tool, so a model can't approve its own proposal.
- **Rules live in code, not in the prompt.** Business rules (source must be a reserve location holding the SKU, quantity can't exceed what's there or overfill the pick face, no duplicate open tasks) are enforced in the service layer and tested.
- **Every tool call is logged** (tool, arguments, result summary, duration, approval decision) and shown in the UI as a collapsible trace.
- **Floor map.** Pick faces colored by stock status (OK, below min, empty, open task), with details on click.
- **Switchable models.** Chat with Claude Opus 5.5, Sonnet 5.5, or Haiku 4.5 from the UI.
- **Also works as an MCP server**, so the same tools can be used from Claude Desktop ([setup](docs/claude-desktop.md)).

## Architecture

```
React chat + floor map  ──HTTP──▶  FastAPI  ──▶  Agent loop (Anthropic SDK, tool use)
                                                       │
                                                       ▼
        MCP server (stdio)  ───────────────▶  services/  (business logic + validation)
                                                       │
                                                       ▼
                                          SQLModel / SQLite (Postgres-ready)
```

Business logic lives in `services/`. The MCP tools, the agent, and the API are thin wrappers around it, so each rule is written and tested once.

The agent loop is hand-written rather than using the SDK's tool runner, because the approval pause can span multiple HTTP requests. Reads run immediately; a write call stops the loop and waits for a person's decision.

| Layer | Choice |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLModel, SQLite (Postgres when deployed) |
| Tools | MCP server (official `mcp` Python SDK) |
| Agent | Anthropic Python SDK, tool use, human approval for writes |
| Front end | React, Vite, TypeScript, Tailwind, shadcn/ui |
| Tooling | uv, ruff, mypy, pytest, Vitest |

## Quick start

You'll need Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js, and an Anthropic API key.

```bash
# 1. Configure
cp .env.example .env          # then set ANTHROPIC_API_KEY

# 2. Backend
cd backend
uv sync
uv run seed-db                # builds a deterministic fake warehouse in backend/warehouse.db
uv run warehouse-api          # http://127.0.0.1:8000

# 3. Front end (new terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

Try: *"Any short picks in zone A today?"*, *"Which pick faces need replenishing, and where's the stock?"*, *"Where is SKU <code> stocked?"*

The seed data is deterministic (fixed random seed), and some pick faces are deliberately planted below minimum so there is always something real to find.

## Tests and quality

```bash
cd backend
uv run pytest                 # unit + integration tests against seeded in-memory SQLite
uv run ruff check . && uv run ruff format --check .
uv run mypy src

cd ../frontend
npm test && npm run lint && npm run typecheck
```

CI runs lint, format check, type check, and tests on every pull request (backend and front end).

## Evals

Unit tests cover the services; the evals measure the *agent*: does Claude pick the right tool, pass the right arguments, and answer correctly? 15 cases (short picks, stock lookup, replenishment needs, write proposals, and boundary cases such as an unknown SKU, a stockout, a duplicate task, an out-of-scope question, and a request to approve its own task) run against the deterministic seeded database. Expected values are looked up from the database at run time, so the cases don't go stale.

```bash
cd backend
uv run python -m warehouse_ops.evals --model claude-haiku-4-5   # calls the Claude API and costs money
```

Results from one run per model (2026-10-02):

| Model | Passed | Tool selection | Arguments | Answers | Outcome | Cost (15 cases) | Mean latency |
|---|---|---|---|---|---|---|---|
| Claude Haiku 4.5 | 15 / 15 | 100% | 100% | 100% | 100% | $0.09 | 3.4 s |
| Claude Sonnet 5.5 | 15 / 15 | 100% | 100% | 100% | 100% | $0.22 | 4.7 s |
| Claude Opus 5.5 | 14 / 15 | 93% | 100% | 100% | 100% | $0.52 | 8.4 s |

- **Cost and speed scale with model size; on these cases accuracy doesn't.** Haiku matched Sonnet at about 40% of the cost and was more than twice as fast as Opus.
- **Opus's one miss is not a safety failure.** Asked to "approve task #1", it correctly refused (no tool can approve) and said there is no such task, but it made a read call first and listed other faces. The case requires no tool calls at all, which is stricter than the rule that matters: the agent never approves or writes on its own.
- **The evals found a real bug.** On Haiku, an early run proposed a duplicate replenishment task because `find_stock` didn't show that one was already open. The service rules would have refused it, but the proposal was wasted. Adding `open_task_id` to `find_stock` fixed it (tool selection 93% to 100%).
- **Caveats:** one run per case, so results vary run to run. Answer checks are keyword-based, so a correct answer with unexpected wording can score as a miss; an LLM judge is the planned fix.

## Project layout

```
backend/src/warehouse_ops/
  db/           SQLModel tables, engine, seed / fake-data generator
  services/     business logic: queries and validation
  mcp_server/   MCP tool wrappers around services/
  agent/        Claude agent loop, approval flow, model options
  api/          FastAPI app for the front end
frontend/       React app: chat, approval cards, tool traces, floor map
docs/           product spec and Claude Desktop setup
```

The full product spec (data model, tools, rules, agent behavior) is in [docs/spec.md](docs/spec.md).

## Status and roadmap

Working today: schema and seed data, services, MCP server, agent loop with approval and logging, FastAPI API, chat UI, floor map, eval runner.

Next:
- [x] Eval set and runner (tool-selection, argument, and answer accuracy, plus cost and latency)
- [ ] Claude-as-judge scoring and repeat runs, to reduce keyword brittleness and run-to-run noise
- [ ] More eval cases (30 to 50 planned)
- [ ] Deployment with Postgres
- [ ] Write-up on design decisions

## Why I built this

<!-- Two or three sentences in your own words: what you wanted to learn and how it connects to your operations background. -->

## License

MIT
