# Warehouse Ops Agent: Spec (v0.2)

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

## Build order

1. Schema + fake-data generator (+ tests for the seed invariants)
2. Services + MCP server, read-only tools first, then `create_replenishment_task`
3. Agent loop with approval + logging; FastAPI endpoints; React chat UI and floor map
4. Eval set and runner
5. Deploy (Postgres), README, write-up

## Out of scope (for v1)

Auth/multi-user, real WMS integration, slotting optimisation, labour planning,
pallet moves other than replenishment (`move_pallet` is a possible v2 tool).
