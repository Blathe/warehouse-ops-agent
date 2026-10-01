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
  status: 'done' | 'needs_approval'
  reply: string
  pending: PendingAction[]
  tool_calls: ToolTrace[]
}

export class ApiError extends Error {}

async function post<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
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

export function sendChat(message: string, conversationId: string | null): Promise<AgentTurn> {
  return post('/api/chat', { message, conversation_id: conversationId })
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
