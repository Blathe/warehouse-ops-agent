# Warehouse Ops Agent: Spec (v0.3)

## Business

The warehouse is the distribution centre for a **fishing tackle and gear** wholesaler/e-commerce brand.
It ships to independent tackle shops, sporting goods retailers, and direct-to-consumer web orders.
Demand is seasonal (spring opener and summer peak), which is when pick faces run dry fastest.

| Zone | Products | Storage notes |
|---|---|---|
| A: Small tackle | Lures, soft plastics, hooks, sinkers, swivels, line spools | Shelving/bin pick faces, high velocity, packs of 6–50 per case |
| B: Rods & reels | Spinning/baitcasting/fly rods, reels, rod & reel combos | Rod racks for long items, low case qty (1–6) |
| C: Bulky gear | Tackle boxes, landing nets, coolers, waders, fish finders | Floor-level pick faces, pallet reserve, low velocity |

## Problem

Pickers go to a pick face and find fewer units than the task expects (a **short pick**).
Usually the stock is sitting in a reserve location, and the pick face simply wasn't
replenished in time. Supervisors find out late and piece the picture together from several screens.

**Goal:** a supervisor asks in plain English ("what's short in zone A this morning and can we fix it?")
and the agent answers from live data, then proposes replenishment moves that the supervisor approves.

## Users

- **Shift supervisor** (primary): chats with the agent, approves replenishment tasks.
- **Replenishment driver** (secondary, implied): receives the approved tasks.
- **Inventory clerk**: cycle counts locations and logs what they find.

## Core concepts

| Term | Meaning |
|---|---|
| Pick location / pick face | Ground-level slot pickers pick from. Holds one SKU, loose units. Has a **min** and **max** qty. |
| Reserve location | Upper rack slot holding full pallets (identified by an LPN) used to refill pick faces. |
| Pick task | "Pick N of SKU X from location L for order line Y." Has `expected_qty` and `picked_qty`. |
| Short pick | A completed pick task where `picked_qty < expected_qty`. |
| Replenishment need | A pick face whose on-hand qty is at or below min, **or** below the open pick demand against it. |
| Replenishment task | A move of qty from a reserve location to a pick face. Created as `PROPOSED`, becomes `APPROVED` only by a human. |

## Data model (SQLModel tables)

- **sku**: id, sku_code, description, brand, category (`LURE` / `SOFT_PLASTIC` / `TERMINAL_TACKLE` / `LINE` /
  `ROD` / `REEL` / `COMBO` / `TACKLE_STORAGE` / `NET` / `COOLER` / `APPAREL` / `ELECTRONICS`), uom (`EA` / `PK` / `SPOOL`),
  case_qty, velocity_class (A/B/C)
- **location**: id, code (`A-03-12-1` = zone-aisle-bay-level), zone, aisle, bay, level,
  type (`PICK` / `RESERVE` / `STAGING`), x, y (for the floor map)
- **pick_face**: location_id (PK), sku_id, min_qty, max_qty
- **inventory**: id, location_id, sku_id, lpn (nullable; set for reserve pallets), qty, received_at
- **picker**: id, name, shift
- **order**: id, order_number, customer, created_at, ship_by, status
- **order_line**: id, order_id, sku_id, qty
- **pick_task**: id, order_line_id, location_id, picker_id, expected_qty, picked_qty (nullable until done),
  status (`OPEN` / `PICKED` / `SHORT`), completed_at
- **replenishment_task**: id, sku_id, from_location_id, to_location_id, lpn, qty, reason,
  status (`PROPOSED` / `APPROVED` / `REJECTED` / `DONE`), created_by, approved_by, created_at, decided_at
- **tool_call_log**: id, ts, session_id, tool, args_json, result_summary, duration_ms, approval (`n/a` / `approved` / `rejected`)

**Seed data** (deterministic, Faker with a fixed seed): ~300 fishing SKUs built from
brand × category × variant word lists (e.g. "Shad Crankbait 2in Firetiger", "7ft Medium Spinning Rod",
"20lb Braided Line 150yd"), fictional brand names, customers that are tackle shops / sporting goods stores / web orders,
3 zones as above, ~400 pick faces + ~800 reserve slots, ~200 orders/day over 3 days, 15 pickers.
Roughly 3–5% of pick faces are planted below min, and some of those produce short picks,
so the tools always have something real to find.

## Tools (MCP)

| Tool | Kind | Input | Returns |
|---|---|---|---|
| `list_short_picks` | read | since?, zone?, sku_code? | short pick tasks with location, SKU, expected vs picked, picker, order |
| `find_stock` | read | sku_code | every location holding the SKU: type, qty, LPN, received_at |
| `list_replenishment_needs` | read | zone?, include_open_demand=true | pick faces needing replen: on-hand, min/max, open demand, suggested qty, best reserve source (FIFO) |
| `create_replenishment_task` | **write** | sku_code, from_location, to_location, qty, reason | the new task in `PROPOSED` status, pending approval |

**Rules for `create_replenishment_task`** (enforced in `services/`, not in the prompt):
from-location is `RESERVE` and holds the SKU; to-location is the SKU's pick face;
0 < qty ≤ qty at source; on-hand + qty ≤ max; no duplicate open task for the same pick face.

**Approval:** a task moves from `PROPOSED` to `APPROVED` or `REJECTED` only through
`decide_replenishment_task(task_id, approve, decided_by)`, which the UI/API calls for a human.
It is deliberately not an MCP tool, so a model can never approve its own proposal.

## Agent behaviour

- Answers only from tool results; says so when data is missing rather than guessing.
- Read tools run freely. Before any write, the agent shows a summary of the proposed task(s)
  and waits for **Approve / Reject** in the UI. A rejection is logged and the agent continues.
- Every tool call is written to `tool_call_log` and shown in the UI as a collapsible trace.

Example conversation:
> **Supervisor:** Any short picks in zone A since 6am?
> **Agent:** 4 short picks, 3 of them on SKU 10442 (2.5in Shad Crankbait, Firetiger) at A-03-12-1 (expected 24, picked 6 in total). Pick face is at 0 / min 12. There's a pallet of 96 in reserve at A-03-12-4. Propose moving 48 to fill to max?
> **Supervisor:** yes → *approval card* → Approve → task #57 created.

## Evals (30–50 questions)

Each case has: the question, the expected tool call(s) and key args, and facts the answer must contain
(checked by exact match where possible, Claude-as-judge otherwise). The runner reports:
**tool selection accuracy**, **argument accuracy**, **answer accuracy**, plus cost and latency.
Include negative cases: an unknown SKU, an over-max replen request (must be refused),
and a question with no data.

## UI

- Chat (shadcn MessageScroller) with tool-call traces and approval cards.
- Floor map: grid of locations by x/y, coloured by status (OK / below min / empty / has open task); click for details.
- Task list: replenishment tasks and their status.
- Crew simulation: a header toggle (off by default). While on, the front end calls
  `POST /api/simulation/tick` every 5 seconds; each tick finishes the oldest APPROVED task
  (ordered by approval time, then id), so the map and task list change as the "crew" works.

## Crew simulation

Finishing a task is a floor event, not something the agent decides, so it is not a tool.
`complete_next_replenishment_task` (in `services/`) takes the oldest APPROVED task and moves
the stock for real: the pick face gains `qty`, the source pallet loses it (an emptied pallet's
slot is freed), and the task becomes DONE. It never touches PROPOSED tasks, so a person always
approves first. If the source pallet no longer holds the quantity it raises a rule violation
(the endpoint answers 409 and the front end switches the simulation off). The endpoint is
serialized with a lock so two overlapping ticks can't finish the same task twice.

## Cycle Count Investigator

**Problem.** Stock drifts away from what the system says: a manual adjustment with a blank
reason, a pallet put away one slot over, a count done in cases instead of eaches. A clerk who
cycle counts a location logs the number and moves on; nobody has time to dig into every
mismatch. When a count doesn't match, a **discrepancy** opens and an AI investigator works out
what most likely happened from the inventory history, with the evidence for each explanation.
The investigator only explains and suggests; a supervisor decides.

### New tables

- **inventory_txn** (the ledger): id, ts, location_id, sku_id, lpn (nullable), qty_change (signed),
  type (`OPENING` / `RECEIVE` / `PICK` / `REPLEN_OUT` / `REPLEN_IN` / `ADJUSTMENT` / `COUNT_ADJUSTMENT`),
  user, reason (may be blank, as in real life), ref (e.g. `pick_task:812`, `replenishment_task:7`).
  **Invariant:** for every location and SKU, the sum of `qty_change` equals the `inventory` qty.
  Every service that changes stock writes its ledger rows in the same transaction.
- **shelf_variance** (hidden truth for the simulation): location_id, sku_id, lpn, delta, scenario.
  What is physically on the shelf minus what the system says. Only the cycle count simulation
  and the evals read it; no tool, prompt or API response exposes it.
- **cycle_count**: id, location_id, sku_id, lpn, counted_by, counted_at, system_qty, counted_qty,
  variance, status (`MATCHED` / `DISCREPANCY` / `RECOUNT_REQUESTED` / `ACCEPTED`),
  resolved_by, resolved_at, resolution_reason.
- **investigation**: id, cycle_count_id, model, status (`RUNNING` / `DONE` / `FAILED`), summary,
  causes (JSON list of {cause, likelihood, evidence[]}), next_steps (JSON list), created_at, tool_calls.

### Seed: history and planted scenarios

The seed writes a ledger for the 3-day window that explains every current quantity: an `OPENING`
row per stock record, `PICK` rows for completed picks, `REPLEN_OUT`/`REPLEN_IN` for done
replenishments, `RECEIVE` rows for recent pallets, and a sprinkle of ordinary `ADJUSTMENT` rows
with sensible reasons ("damaged in handling", "found during putaway") as background noise.
Staff names are seeded for clerks and supervisors so every row has a user.

Six planted scenarios, each with a true cause the investigator should find:

| Scenario | What the count finds | Evidence in the data |
|---|---|---|
| `blank_adjustment` | Pick face short by N | An `ADJUSTMENT` of +N with a blank reason by one user, likely keyed against the wrong location |
| `mis_slot` | A reserve slot is missing its whole pallet; a nearby empty slot holds a pallet | Same LPN and qty; the pallet was put away one slot over |
| `case_vs_each` | A reserve pallet counted at qty ÷ case_qty | Variance is exactly qty − qty/case_qty; the counted number × case_qty matches the system |
| `short_replen` | Pick face short by N, its source pallet over by N | A `DONE` replenishment of Q from that pallet; the crew moved Q − N |
| `mid_pick_count` | Pick face short by the qty of an open pick | An `OPEN` pick task at the face for exactly that qty; a recount after the pick matches |
| `unexplained_shrink` | Pick face short by a few units | Nothing; the honest answer is "no evidence, likely damage or theft; recount and check the damage bin" |

### Simulating a cycle count

A **Simulate cycle count** button (`POST /api/simulation/cycle-count`) counts about 30 locations:
every planted location plus a random sample of others, as a clerk would on a normal shift. Each
counted qty is the system qty plus that location's `shelf_variance` (zero for most), so most
counts match and 6–7 open as discrepancies. Locations with a `RECOUNT_REQUESTED` count are
included again; a recount of `mid_pick_count` after the pick is confirmed matches.

### Investigation

Every new discrepancy is investigated automatically in the background, on a low-cost model
(`claude-sonnet-5-5` by default, configurable). The investigator gets read-only tools:

| Tool | Returns |
|---|---|
| `list_discrepancies` | open discrepancies with location, SKU, system vs counted, variance |
| `get_inventory_history` | ledger rows for a location and/or SKU over a time window |
| `find_stock` | (existing) every location holding a SKU |
| `get_nearby_stock` | stock and recent counts in the neighbouring bays and slots |
| `list_open_picks` | open pick tasks at a location |

It ends by calling `submit_findings` (validated; an invalid submission gets one more try) and
returns a summary, likely causes ranked with evidence that cites ledger rows, and next steps
(recount, check a named location, ask a named user). The same tools are available to the chat,
so a supervisor can ask "why is A-03-04-1 off?".

Investigations run in a background thread pool (4 at a time) after the count's response is
sent, so the page shows them as running and polls until they finish. A failed investigation
(no API key, an API error) records a readable error and can be run again from the page.
`INVESTIGATOR_MODEL` overrides the model. The simulated count shows a progress bar for a few
seconds, so it feels like a clerk walking the aisles.

### Resolving a discrepancy (human only)

- **Accept**: writes a `COUNT_ADJUSTMENT` so the system matches the count. A reason is required,
  so the system never gets another blank one.
- **Recount**: sets `RECOUNT_REQUESTED`; the next simulated count includes the location again.

Like approval, resolving is never an agent or MCP tool.

### UI

- **Cycle counts** page next to Tasks: open discrepancies first, each with system vs counted,
  the investigation (summary, causes with evidence, next steps), and Accept / Recount buttons.
- Floor map: bays with an open discrepancy get a marker.
- Activity feed: counts logged, discrepancies opened, investigations finished, resolutions.

### Delivery

1. Ledger, staff, seeded history and planted scenarios (+ the crew simulation writes ledger rows)
2. Cycle counts, discrepancies, the simulate button and the Cycle counts page with Accept / Recount
3. Investigator: read-only tools, background investigation, results on the page and in the chat

## Build order

1. Schema + fake-data generator (+ tests for the seed invariants)
2. Services + MCP server, read-only tools first, then `create_replenishment_task`
3. Agent loop with approval + logging; FastAPI endpoints; React chat UI and floor map
4. Eval set and runner
5. Deploy (Postgres), README, write-up

## Out of scope (for v1)

Auth/multi-user, real WMS integration, slotting optimisation, labour planning,
pallet moves other than replenishment (`move_pallet` is a possible v2 tool).
