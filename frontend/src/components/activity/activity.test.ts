import { describe, expect, it } from 'vitest'

import type { AgentTurn, ToolTrace } from '@/lib/api'
import { activityFromTurn, describeToolCall, locationsInTurn } from './activity'

const move = {
  sku_code: '58368',
  from_location: 'A-03-06-2',
  to_location: 'A-03-04-1',
  qty: 144,
  reason: 'empty',
}

function call(overrides: Partial<ToolTrace>): ToolTrace {
  return { tool: 'list_replenishment_needs', input: {}, ok: true, summary: '13 results', approval: 'n/a', ...overrides }
}

function turn(overrides: Partial<AgentTurn>): AgentTurn {
  return {
    conversation_id: 'c1',
    model: 'claude-opus-5-5',
    status: 'done',
    reply: '',
    pending: [],
    tool_calls: [],
    ...overrides,
  }
}

describe('describeToolCall', () => {
  it('describes reads', () => {
    expect(describeToolCall(call({ input: { zone: 'A' } }))).toEqual({
      title: 'Checked replenishment needs in zone A',
      detail: '13 results',
      tone: 'info',
    })
    expect(describeToolCall(call({ tool: 'find_stock', input: { sku_code: '58368' } })).title).toBe(
      'Found stock for SKU 58368',
    )
  })

  it('describes approved, rejected and refused moves', () => {
    const base = { tool: 'create_replenishment_task', input: move }
    expect(describeToolCall(call({ ...base, approval: 'approved' }))).toMatchObject({
      title: 'Replenishment task approved',
      detail: '144 × SKU 58368 from A-03-06-2 to A-03-04-1',
      tone: 'success',
    })
    expect(describeToolCall(call({ ...base, approval: 'rejected', ok: false })).tone).toBe('warning')
    expect(
      describeToolCall(
        call({ ...base, approval: 'approved', ok: false, summary: 'error: at most 96 can be added' }),
      ),
    ).toMatchObject({ title: 'Replenishment refused', detail: 'at most 96 can be added', tone: 'error' })
  })
})

describe('activityFromTurn', () => {
  it('lists tool calls, then pending approvals', () => {
    const items = activityFromTurn(
      turn({
        tool_calls: [call({})],
        pending: [{ tool_use_id: 't1', tool: 'create_replenishment_task', input: move }],
      }),
    )
    expect(items.map((i) => i.title)).toEqual([
      'Checked replenishment needs',
      'Waiting for your approval',
    ])
  })
})

describe('locationsInTurn', () => {
  it('maps reserve slots to their pick face, destination first, without duplicates', () => {
    const locations = locationsInTurn(
      turn({
        pending: [{ tool_use_id: 't1', tool: 'create_replenishment_task', input: move }],
        tool_calls: [call({ input: { to_location: 'a-03-04-1' } })],
      }),
    )
    expect(locations).toEqual(['A-03-04-1', 'A-03-06-1'])
  })
})
