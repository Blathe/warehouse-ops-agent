# Agent Log: plan

A page that lists everything the agent did (tool calls, approval decisions, cycle count
investigations) with what each step cost, and a running total at the top.

## Scope

**v1:** tool calls, approvals, investigator runs, cost.
**Later:** chat transcripts (user prompts and final answers), a link from a task to the
calls that proposed it, a cost-over-time chart.

## Key finding: cost belongs to model calls, not tool calls

A tool call is free to run. The money is spent on each Claude request (`beta.messages.create`),
and one response can ask for several tools at once. So cost is stored per **model call**
and shown against the tool calls that response requested.

Today `tool_call_log` has no token data, and only the eval harness meters usage
(`evals/common.py`, `cost_usd`). The chat agent (`agent/loop.py`) and the investigator
(`agent/investigator.py`) throw `response.usage` away. This is the main new work.

No prompt caching is used, so `input_tokens + output_tokens` is the full cost. If caching is
added later, `cost_usd` needs the cache read/write rates.

## Data model

New table `model_call_log`, one row per Claude request:

| Column | Notes |
|---|---|
| `id` | PK |
| `ts` | real time (`clock.wall_now`), not the pinned warehouse clock, so a log row says when it happened |
| `session_id` | same values as `tool_call_log` (conversation id, `investigation:<id>`) |
| `source` | `CHAT`, `INVESTIGATOR` or `MCP` (`LogSource`) |
| `model` | model id |
| `input_tokens`, `output_tokens` | from `response.usage` |
| `cost_usd` | computed at write time from `MODEL_OPTIONS`, so later price changes don't rewrite history |
| `duration_ms` | |
| `stop_reason` | `tool_use`, `end_turn`, `refusal`, ... |

Changes to `tool_call_log` (Alembic is not used here, so the seed/`create_all` path covers it):

- `model_call_id` (nullable FK): the model call that requested this tool. Null for MCP calls,
  which come from Claude Desktop and have no cost we can see.
- `source` (same values as above). Backfill is not needed because the seeded DB is rebuilt;
  existing local DBs get re-seeded.

Move `cost_usd` out of `evals/common.py` into a shared module (`agent/pricing.py`) so the
agent, the investigator and the evals use one formula.

## Where cost gets recorded

- `Agent._run` (`loop.py`): after each `create`, write a `model_call_log` row and pass its id
  to `execute_tool_call` / `record_tool_call`. Rejected writes (`_reject`) link to the same id.
- `Investigator.run`: same, with `source="investigator"`.
- Evals: not shown on the page. Their cost is already in the eval reports, and they run on a
  throwaway in-memory DB. (They go through the same `Agent`, so they log there, harmlessly.)
- MCP server: unchanged, rows keep `source="mcp"` with no cost.

## Backend API

Service in `services/agent_log.py` (plain functions, read-only session):

- `list_agent_log(session, *, session_id, tool, source, approval, since, until, cursor, limit)`
  returns entries newest first, with cursor pagination (`ts`, `id`).
- `summarize_agent_log(session, *, same filters)` returns total cost, model call count, tool
  call count, and cost by model and by source.
- `list_agent_sessions(session, ...)` returns one row per session: first/last time, source,
  tool call count, cost, and whether any call was rejected.

Endpoints (thin wrappers in `api/app.py`):

- `GET /api/agent-log` entries
- `GET /api/agent-log/summary` totals for the header
- `GET /api/agent-log/sessions` grouped view

The summary respects the filters, so "total cost" at the top always matches what is shown.
With no filters it is the cost of all logs.

## Hidden truth

`shelf_variance` must never reach the log. Services should not return it to the agent, so it
should not appear in `args_json` or `result_summary`. Add a test in `tests/services/` that
runs the investigator and chat tools against the seeded DB, then asserts that no logged row
contains `shelf_variance` (or its values for the seeded counts). It also covers the new
API responses.

## Front end

New page `/agent-log` ("Agent log", `ScrollTextIcon`) added to `PAGES` in `layout/pages.ts`.

- **Header:** total cost, model calls, tool calls, and a small breakdown by model/source.
- **Filters:** source (chat / investigator / mcp), tool, approval, date range.
  Investigator rows are shown by default.
- **Sessions list:** collapsible rows, one per `session_id`, showing source badge, start time,
  call count, cost, and a rejected badge. Expanding a row shows its steps in order.
- **Step rows:** time, tool, approval badge (reuse the `Badge` pattern from `tasks/status.ts`),
  duration, cost. Cost is shown on the first tool call of each model call, with a "model call"
  line above the group (model, tokens, cost) so parallel calls aren't double counted.
- **Detail:** expanding a step shows the formatted args and the result summary.
- Flat/"all calls" toggle for people who want the raw list.
- Cost format: `$0.0123` (four decimals, since single calls are fractions of a cent).

## PRs (small, one feature each)

1. `feat/model-call-log`: `model_call_log` table, `source` and `model_call_id` columns,
   shared `pricing.py`, recording in `Agent` and `Investigator`. Tests: a fake client with a
   known `usage` produces the expected rows and cost, tool calls link to the right model call.
2. `feat/agent-log-api`: service plus three endpoints, filters, pagination, the
   `shelf_variance` test. Tests against the seeded DB.
3. `feat/agent-log-page`: the page, with component tests like `TasksPage.test.tsx`.
4. `docs/agent-log`: README/spec update and a screenshot. Can be folded into PR 3.

## Decisions

- Eval runs are not in the page (their cost is in the eval reports).
- Retention: the log only grows. Fine for a portfolio project; no pruning in v1.
