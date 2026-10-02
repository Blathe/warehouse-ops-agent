import type { AgentTurn, PendingAction, ReplenishmentTask, ToolTrace } from '@/lib/api'

export type Tone = 'info' | 'success' | 'warning' | 'error'

export interface ActivityItem {
  id: number
  at: Date
  title: string
  detail: string
  tone: Tone
}

let nextId = 1

function str(value: unknown): string {
  return value === undefined || value === null ? '' : String(value)
}

// "144 × SKU 58368 from A-03-06-2 to A-03-04-1"
export function describeMove(input: Record<string, unknown>): string {
  return `${str(input.qty)} × SKU ${str(input.sku_code)} from ${str(input.from_location)} to ${str(input.to_location)}`
}

// Turns one tool call from the agent into a line a supervisor can read.
export function describeToolCall(call: ToolTrace): Omit<ActivityItem, 'id' | 'at'> {
  const input = call.input
  if (call.tool === 'create_replenishment_task') {
    if (call.approval === 'rejected') {
      return { title: 'Replenishment rejected', detail: describeMove(input), tone: 'warning' }
    }
    if (!call.ok) {
      return { title: 'Replenishment refused', detail: call.summary.replace(/^error: /, ''), tone: 'error' }
    }
    return { title: 'Replenishment task approved', detail: describeMove(input), tone: 'success' }
  }
  if (!call.ok) {
    return { title: `${call.tool} failed`, detail: call.summary.replace(/^error: /, ''), tone: 'error' }
  }
  const zone = input.zone ? ` in zone ${str(input.zone)}` : ''
  switch (call.tool) {
    case 'list_replenishment_needs':
      return { title: `Checked replenishment needs${zone}`, detail: call.summary, tone: 'info' }
    case 'list_short_picks':
      return { title: `Looked up short picks${zone}`, detail: call.summary, tone: 'info' }
    case 'find_stock':
      return { title: `Found stock for SKU ${str(input.sku_code)}`, detail: '', tone: 'info' }
    default:
      return { title: call.tool, detail: call.summary, tone: 'info' }
  }
}

export function describePending(action: PendingAction): Omit<ActivityItem, 'id' | 'at'> {
  return { title: 'Waiting for your approval', detail: describeMove(action.input), tone: 'warning' }
}

// Activity lines for one agent turn: its tool calls, then anything awaiting approval.
export function activityFromTurn(turn: AgentTurn, at = new Date()): ActivityItem[] {
  return [
    ...turn.tool_calls.map(describeToolCall),
    ...turn.pending.map(describePending),
  ].map((item) => ({ ...item, id: nextId++, at }))
}

// A line that didn't come from an agent turn, e.g. from the crew simulation.
export function activityNote(title: string, detail: string, tone: Tone, at = new Date()): ActivityItem {
  return { id: nextId++, at, title, detail, tone }
}

// The simulated floor crew finished a task.
export function activityFromCompletion(task: ReplenishmentTask): ActivityItem {
  return activityNote(
    `Crew completed task #${task.task_id}`,
    `${task.qty} × SKU ${task.sku_code} from ${task.from_location} to ${task.to_location}`,
    'success',
  )
}

// Pick face codes the turn touches, so the map can highlight them. A reserve slot
// (A-03-06-2) belongs to the bay whose pick face is A-03-06-1.
export function locationsInTurn(turn: AgentTurn): string[] {
  const inputs = [...turn.pending.map((p) => p.input), ...turn.tool_calls.map((c) => c.input)]
  const codes = inputs.flatMap((input) => [input.to_location, input.from_location])
  return [
    ...new Set(
      codes
        .filter((code): code is string => typeof code === 'string')
        .map((code) => code.trim().toUpperCase().replace(/-\d$/, '-1')),
    ),
  ]
}
