# Warehouse Ops Agent

A Claude-powered assistant for a warehouse shift supervisor, built over a realistic database for a fishing tackle distribution center. It does two jobs:

- **Short picks and replenishment.** "Any short picks in zone A since 6am?" The agent queries live data, explains what happened, and proposes a replenishment move. A person approves it; the model never approves its own work.
- **Cycle Count Investigator.** When a cycle count doesn't match the system, an AI investigator digs through the inventory history and explains what most likely happened, with evidence, before a supervisor decides what to do.

<!-- TODO: add a screenshot or GIF of the chat + floor map here (docs/demo.gif) -->

## The problem

A picker goes to a pick face and finds fewer units than the task expects: a **short pick**. Usually the stock is sitting on a pallet in reserve, and the pick face just wasn't refilled in time. Supervisors find out late and piece the picture together from several screens.

This agent lets a supervisor ask what's short, find where the stock is, and queue the fix from one chat.

The second problem is **inventory that drifts** from what the system says: a manual adjustment entered with a blank reason, a pallet put away one slot over, a pallet counted in cases instead of units. A clerk who cycle counts a location logs the number and moves on; nobody has time to investigate every mismatch, so the same errors keep coming back. The Cycle Count Investigator does that legwork for every mismatch, automatically.

## What it does

- **Answers from data, not guesses.** Four tools query the warehouse database (short picks, stock by SKU, pick faces needing replenishment, and a write tool to create replenishment tasks). The agent is instructed to say so when data is missing.
- **Human-only approval for writes.** The agent can only *propose* a replenishment task. When it does, the loop pauses and the UI shows an approval card. Approving or rejecting is exposed to the UI/API only, never as an agent or MCP tool, so a model can't approve its own proposal.
- **Rules live in code, not in the prompt.** Business rules (source must be a reserve location holding the SKU, quantity can't exceed what's there or overfill the pick face, no duplicate open tasks) are enforced in the service layer and tested.
- **Every tool call is logged** (tool, arguments, result summary, duration, approval decision) and shown in the UI as a collapsible trace.
- **Floor map.** Its own page: zones laid out with the dock and aisles, pick faces colored by stock status (OK, below min, empty, open task) or shaded by fill level, a zone filter, a hover card per bay and full stock details on click.
- **Simulated floor crew.** A toggle in the settings menu (bottom of the sidebar; off by default, with a "Crew running" indicator in the header while it runs) finishes one approved task every 5 seconds, oldest first, and moves the stock for real, so the map and task count change live as the warehouse "works". The agent can't do this: completing a task is not a tool.
- **Switchable models.** Chat with Claude Opus 5.5, Sonnet 5.5, or Haiku 4.5 from the UI.
- **Also works as an MCP server**, so the same tools can be used from Claude Desktop ([setup](docs/claude-desktop.md)).
- **Chat.** Chat on the left and an activity feed of everything the agent did on the right, with a draggable divider whose position is remembered. After each reply the floor map highlights the bays the agent is working on, one click away. An **Overview** page is the landing page, and a **Tasks** page lists every replenishment task.
- **Quick navigation.** Press **Ctrl+K** (⌘K on a Mac) to jump to a page, flip dark mode, start the crew simulation or find a pick face by location, SKU or product name. Toasts report approvals, finished crew tasks and cycle counts wherever you are in the app.

### Cycle Count Investigator

- **An inventory ledger.** Every stock change (receipts, picks, replenishment moves, manual adjustments) is recorded with who did it, when, the reason and what caused it. The ledger always sums to the current stock, and a test enforces it.
- **Simulate a cycle count.** One click counts about 30 locations the way a clerk would on a shift. Six problems are planted in the seed data, each with a known cause, so most counts match and 8 discrepancies open.
- **Automatic AI investigation.** Each discrepancy is investigated in the background by a separate, lower-cost model with read-only tools: inventory history with running balances, nearby slots, unconfirmed picks, and the other open discrepancies. It returns a summary, likely causes ranked with evidence (for example, "+30 adjustment by Michael Mcguire, May 30, no reason given"), and next steps.
- **People decide.** Accepting a count (which adjusts the system and requires a reason) or requesting a recount is a supervisor's click, never a tool. On a recount, counting mistakes and picks that were in progress clear up; real losses show up again.
- **The chat can investigate too:** "why is A-02-23-1 off?" uses the same read-only tools. The hidden ground truth is only ever read by the simulation and the evals, never by a model.

## Architecture

```
React chat + floor map  ──HTTP──▶  FastAPI  ──▶  Agent loop (Anthropic SDK, tool use)
                                                       │
                                                       ▼
        MCP server (stdio)  ───────────────▶  services/  (business logic + validation)
                                                       ▲
  Cycle count ──▶ discrepancies ──▶ Investigator (background, read-only tools)
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

Try: *"Any short picks in zone A today?"*, *"Which pick faces need replenishing, and where's the stock?"*, *"Where is SKU <code> stocked?"* Then open **Cycle counts**, click **Simulate cycle count**, and watch the investigations come in.

### Docker (whole app)

If you'd rather not install Python and Node, you only need [Docker](https://www.docker.com/) and an `.env` with your `ANTHROPIC_API_KEY`. From the repo root:

```bash
docker build -t warehouse-ops .
docker run --rm -p 8000:8000 --env-file .env warehouse-ops
```

Then open http://localhost:8000. Stop it with Ctrl+C.

- **One container runs everything.** A Node stage builds the React app, and FastAPI serves it next to the API, so there is no Vite dev server and no proxy.
- **It resets on every start.** The image seeds a fresh SQLite database at build time (`--as-of 2026-06-01T13:00`, with `WAREHOUSE_AS_OF` pinned to match), so each container starts from the same warehouse. Approved tasks and chat history are gone after a restart.
- **Port 8000 busy?** Map another host port, e.g. `-p 8001:8000`, and open http://localhost:8001.
- **No key?** Leave off `--env-file`. The app still loads and the data pages work; only chat and investigations need the key.
- **The API key is never baked into the image.** `.env` is excluded by `.dockerignore` and passed at run time.
- **Not for the public internet yet.** There is no auth or spend cap, so don't expose it with a real key.

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
uv run run-evals --model claude-haiku-4-5   # calls the Claude API and costs money
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

### Investigator evals

A second suite checks whether the investigator finds the **true cause** of each planted discrepancy. There are 8 cases, one per discrepancy, each scored on the top-ranked cause, whether the right cause is in the top 3, the evidence cited (such as the adjusting user, or the neighbouring slot of a misplaced pallet), the tools used, and the next steps. For the one problem the data can't explain, the right answer is to say so rather than invent a cause.

```bash
uv run run-evals --suite investigator --model claude-haiku-4-5
uv run run-evals --suite investigator --rescore evals/results/<report>.json   # regrade, no API calls
```

Results from one run per model (2026-10-04):

| Investigator model | Correct root cause | Evidence cited | Right tools | Cost (8 investigations) | Mean latency |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | 7 / 8 | 100% | 100% | $0.16 | 13 s |
| Claude Opus 5.5 | 8 / 8 | 100% | 100% | $0.94 | 14 s |

- **Haiku is the value pick:** about 2¢ per investigation versus 12¢. Its one miss was a pallet counted in cases instead of units: it guessed that stock had been removed, and its arithmetic was wrong. Opus spotted the miscount and suggested checking the same clerk's other counts.
- **The evals caught mistakes in the eval itself.** The first run showed that one planted problem had an accidental red herring (an unconfirmed pick of 11 next to a shortage of 12), so I fixed the seed. Later runs showed the keyword checks failing correct answers ("refill" instead of "replenishment"), so I broadened them and added `--rescore` to regrade saved reports for free. An LLM judge is the next step to make the scoring sturdier.

## Project layout

```
backend/src/warehouse_ops/
  db/           SQLModel tables, engine, seed / fake-data generator, seeded history and planted scenarios
  services/     business logic: queries, validation, cycle counts, the inventory ledger
  mcp_server/   MCP tool wrappers around services/
  agent/        Claude agent loop, approval flow, model options, cycle count investigator
  api/          FastAPI app for the front end
  evals/        eval runner and scoring for both suites
backend/evals/  eval cases (cases.yaml, investigations.yaml) and run reports
frontend/       React app: chat, approval cards, tool traces, floor map, Tasks, Cycle counts and Agent log pages
docs/           product spec and Claude Desktop setup
Dockerfile      one image for the React app, API and agent (SQLite)
```

The full product spec (data model, tools, rules, agent behavior) is in [docs/spec.md](docs/spec.md).

## Status and roadmap

Working today: schema and seed data, services, MCP server, agent loop with approval and logging, FastAPI API, chat UI, floor map, crew simulation, Cycle Count Investigator, and both eval suites.

Next:
- [x] Eval set and runner (tool-selection, argument, and answer accuracy, plus cost and latency)
- [x] Cycle Count Investigator with its own eval suite
- [ ] Claude-as-judge scoring and repeat runs, to reduce keyword brittleness and run-to-run noise
- [ ] More eval cases (30 to 50 planned)
- [x] Dockerfile: the whole app in one container on SQLite
- [ ] Hosted deployment with Postgres, auth and a spend cap
- [ ] Write-up on design decisions

## Why I built this

I love warehouse operations. I spent seven years building internal warehouse tools, and I'm fascinated by how AI can start to merge into that work: not replacing the people on the floor, but taking on the digging and cross-checking that nobody has time for. The Cycle Count Investigator is the kind of tool that would have saved me hundreds of hours at my last job.

This is a learning project. I built it to get hands-on with AI engineering and automation workflows: tool use, human-in-the-loop approval, MCP, and evals that measure whether a model actually gets things right. Retrieval (RAG) is next on my list. Even so, I designed it around real warehouse problems and real constraints, so that a version of it could realistically help run a warehouse one day.

## License

MIT
