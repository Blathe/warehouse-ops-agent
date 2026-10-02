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
}

export interface FloorMapData {
  bays: Bay[]
  staging: { location: string; x: number; y: number }[]
  counts: Record<PickStatus, number>
}

export function getFloorMap(): Promise<FloorMapData> {
  return request('/api/floor-map')
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
