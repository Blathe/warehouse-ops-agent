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
