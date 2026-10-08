// Client for the FastAPI backend. Vite proxies /api to http://127.0.0.1:8000 in dev.
// These types mirror the Pydantic models in backend/src/warehouse_ops/agent/loop.py.

export type Approval = 'n/a' | 'approved' | 'rejected'

export interface ToolTrace {
  tool: string
  input: Record<string, unknown>
  ok: boolean
  summary: string
  approval: Approval
}

export interface PendingAction {
  tool_use_id: string
  tool: string
  input: Record<string, unknown>
}

export interface AgentTurn {
  conversation_id: string
  model: string
  status: 'done' | 'needs_approval'
  reply: string
  pending: PendingAction[]
  tool_calls: ToolTrace[]
}

export interface ModelOption {
  id: string
  label: string
  input_per_mtok: number // USD per million input tokens
  output_per_mtok: number
}

export interface ModelsResponse {
  default: string
  models: ModelOption[]
}

export class ApiError extends Error {}

async function post<T>(url: string, body: unknown): Promise<T> {
  return request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    // FastAPI errors look like {"detail": "..."}; validation errors have a list instead.
    const data: unknown = await response.json().catch(() => null)
    const detail = (data as { detail?: unknown } | null)?.detail
    throw new ApiError(
      typeof detail === 'string' ? detail : `Request failed (${response.status})`,
    )
  }
  return (await response.json()) as T
}

export function getModels(): Promise<ModelsResponse> {
  return request('/api/models')
}

export function sendChat(
  message: string,
  conversationId: string | null,
  model: string | null,
): Promise<AgentTurn> {
  return post('/api/chat', { message, conversation_id: conversationId, model })
}

export function sendApproval(
  conversationId: string,
  approve: boolean,
  decidedBy: string,
): Promise<AgentTurn> {
  return post(`/api/conversations/${conversationId}/approval`, {
    approve,
    decided_by: decidedBy,
  })
}

export type PickStatus = 'ok' | 'low' | 'empty' | 'unassigned'

export interface PickSlot {
  location: string
  sku_code: string | null
  description: string | null
  on_hand: number
  min_qty: number | null
  max_qty: number | null
  status: PickStatus
  open_task_id: number | null
}

export interface ReserveSlot {
  location: string
  level: number
  sku_code: string | null
  lpn: string | null
  qty: number
}

export interface Bay {
  zone: string
  aisle: number
  bay: number
  x: number
  y: number
  pick: PickSlot
  reserve: ReserveSlot[]
  open_discrepancies: string[] // location codes in this bay with an open count
}

export interface FloorMapData {
  bays: Bay[]
  staging: { location: string; x: number; y: number }[]
  counts: Record<PickStatus, number>
}

export function getFloorMap(): Promise<FloorMapData> {
  return request('/api/floor-map')
}

// Mirrors Overview in backend/src/warehouse_ops/services/overview.py.
export interface ZoneHealth {
  zone: string
  ok: number
  low: number
  empty: number
  unassigned: number
  short_picks: number // in the last 24 hours
}

export interface UrgentNeed {
  location: string
  zone: string
  sku_code: string
  description: string
  on_hand: number
  min_qty: number
  max_qty: number
  open_demand: number
  reasons: string[]
  suggested_qty: number
}

export interface OverviewData {
  as_of: string
  empty_faces: number
  low_faces: number
  short_picks_24h: number
  tasks_awaiting_approval: number
  tasks_approved: number
  open_discrepancies: number
  zones: ZoneHealth[]
  short_picks_by_hour: { hour_start: string; short_picks: number }[] // oldest first
  urgent_needs: UrgentNeed[]
}

export function getOverview(): Promise<OverviewData> {
  return request('/api/overview')
}

export type TaskStatus = 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'DONE'
export type TaskFilter = 'active' | 'done' | 'rejected' | 'all'

// Mirrors ReplenishmentTaskOut in backend/src/warehouse_ops/services/schemas.py.
export interface ReplenishmentTask {
  task_id: number
  status: TaskStatus
  sku_code: string
  description: string
  from_location: string
  to_location: string
  lpn: string | null
  qty: number
  reason: string
  created_by: string
  created_at: string // warehouse local time, no UTC offset
  approved_by: string | null // who approved or rejected it
  decided_at: string | null
}

export function getTasks(filter: TaskFilter = 'active'): Promise<ReplenishmentTask[]> {
  return request(`/api/tasks?status=${filter}`)
}

export interface TickResponse {
  completed: ReplenishmentTask | null // null when no approved task was waiting
}

// Simulated floor crew: the backend finishes the oldest approved task and moves its stock.
export function tickSimulation(): Promise<TickResponse> {
  return post('/api/simulation/tick', {})
}

export type CountStatus = 'MATCHED' | 'DISCREPANCY' | 'RECOUNT_REQUESTED' | 'RECOUNTED' | 'ACCEPTED'
export type CountFilter = 'open' | 'resolved' | 'all'

export type InvestigationStatus = 'RUNNING' | 'DONE' | 'FAILED'

export interface Cause {
  cause: string
  likelihood: 'high' | 'medium' | 'low'
  evidence: string[]
}

export interface Investigation {
  id: number
  status: InvestigationStatus
  model: string
  summary: string | null
  causes: Cause[]
  next_steps: string[]
  error: string | null
  tool_calls: number
  started_at: string
  finished_at: string | null
}

export interface CycleCount {
  id: number
  location: string
  sku_code: string
  description: string
  case_qty: number
  lpn: string | null
  counted_by: string
  counted_at: string
  system_qty: number
  counted_qty: number
  variance: number // counted - system
  status: CountStatus
  resolved_by: string | null
  resolved_at: string | null
  resolution_reason: string | null
  investigation: Investigation | null // the latest AI investigation
}

export interface CycleCountRun {
  counted: number
  matched: number
  discrepancies: CycleCount[]
}

export function simulateCycleCount(): Promise<CycleCountRun> {
  return post('/api/simulation/cycle-count', {})
}

export function getCycleCounts(filter: CountFilter = 'open'): Promise<CycleCount[]> {
  return request(`/api/cycle-counts?status=${filter}`)
}

export function acceptCycleCount(id: number, decidedBy: string, reason: string): Promise<CycleCount> {
  return post(`/api/cycle-counts/${id}/accept`, { decided_by: decidedBy, reason })
}

export function requestRecount(id: number, decidedBy: string): Promise<CycleCount> {
  return post(`/api/cycle-counts/${id}/recount`, { decided_by: decidedBy })
}

export function investigateAgain(id: number): Promise<CycleCount> {
  return post(`/api/cycle-counts/${id}/investigate`, {})
}

// The agent log. These types mirror backend/src/warehouse_ops/services/agent_log.py.
export type LogSource = 'CHAT' | 'INVESTIGATOR' | 'MCP'

export interface ToolCallEntry {
  id: number
  ts: string
  session_id: string
  source: LogSource
  tool: string
  args: Record<string, unknown>
  result_summary: string
  duration_ms: number
  approval: Approval
  model_call_id: number | null
  model: string | null
  model_call_cost_usd: number | null // shared by every call from the same request
}

export interface ModelCallEntry {
  id: number
  ts: string
  session_id: string
  source: LogSource
  model: string
  input_tokens: number
  output_tokens: number
  cost_usd: number
  duration_ms: number
  stop_reason: string | null
}

// One Claude request and the tool calls it asked for (model_call is null for MCP calls).
export interface LogStep {
  model_call: ModelCallEntry | null
  tool_calls: ToolCallEntry[]
}

export interface CostBreakdown {
  key: string
  cost_usd: number
  model_calls: number
  tool_calls: number
}

export interface LogSummary {
  total_cost_usd: number
  model_calls: number
  tool_calls: number
  sessions: number
  input_tokens: number
  output_tokens: number
  by_model: CostBreakdown[]
  by_source: CostBreakdown[]
}

export interface SessionSummary {
  session_id: string
  source: LogSource
  started_at: string
  last_at: string
  model_calls: number
  tool_calls: number
  cost_usd: number
  rejected: number
}

export interface LogFilters {
  source?: LogSource
  since?: string // warehouse local time, e.g. 2026-06-01T00:00:00
  until?: string
}

export interface CallFilters extends LogFilters {
  tool?: string
  approval?: Approval
  before_id?: number // the last id of the previous page
  limit?: number
}

// Builds ?a=1&b=2, skipping empty values.
function query(params: object): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export function getAgentLogSummary(filters: LogFilters = {}): Promise<LogSummary> {
  return request(`/api/agent-log/summary${query(filters)}`)
}

export function getAgentSessions(filters: LogFilters = {}): Promise<SessionSummary[]> {
  return request(`/api/agent-log/sessions${query(filters)}`)
}

export function getSessionSteps(sessionId: string): Promise<LogStep[]> {
  return request(`/api/agent-log/sessions/${encodeURIComponent(sessionId)}`)
}

export function getAgentCalls(filters: CallFilters = {}): Promise<ToolCallEntry[]> {
  return request(`/api/agent-log${query(filters)}`)
}
