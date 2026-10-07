import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { LogStep, LogSummary, SessionSummary, ToolCallEntry } from '@/lib/api'
import { AgentLogPage } from './AgentLogPage'

function call(overrides: Partial<ToolCallEntry> = {}): ToolCallEntry {
  return {
    id: 1,
    ts: '2026-06-01T13:00:00',
    session_id: 'abc12345def',
    source: 'CHAT',
    tool: 'find_stock',
    args: { sku_code: '10442' },
    result_summary: '3 results',
    duration_ms: 12,
    approval: 'n/a',
    model_call_id: 1,
    model: 'claude-opus-5-5',
    model_call_cost_usd: 0.006,
    ...overrides,
  }
}

const summary: LogSummary = {
  total_cost_usd: 2.0183,
  model_calls: 3,
  tool_calls: 5,
  sessions: 2,
  input_tokens: 1_003_000,
  output_tokens: 300,
  by_model: [
    { key: 'claude-sonnet-5-5', cost_usd: 2, model_calls: 1, tool_calls: 0 },
    { key: 'claude-opus-5-5', cost_usd: 0.0183, model_calls: 2, tool_calls: 0 },
  ],
  by_source: [
    { key: 'CHAT', cost_usd: 0.0183, model_calls: 2, tool_calls: 3 },
    { key: 'INVESTIGATOR', cost_usd: 2, model_calls: 1, tool_calls: 1 },
  ],
}

const sessions: SessionSummary[] = [
  {
    session_id: 'investigation:7',
    source: 'INVESTIGATOR',
    started_at: '2026-06-01T13:10:00',
    last_at: '2026-06-01T13:11:00',
    model_calls: 1,
    tool_calls: 1,
    cost_usd: 2,
    rejected: 0,
  },
  {
    session_id: 'abc12345def',
    source: 'CHAT',
    started_at: '2026-06-01T13:00:00',
    last_at: '2026-06-01T13:03:00',
    model_calls: 2,
    tool_calls: 3,
    cost_usd: 0.0183,
    rejected: 1,
  },
]

const steps: LogStep[] = [
  {
    model_call: {
      id: 1,
      ts: '2026-06-01T13:00:00',
      session_id: 'abc12345def',
      source: 'CHAT',
      model: 'claude-opus-5-5',
      input_tokens: 1000,
      output_tokens: 100,
      cost_usd: 0.006,
      duration_ms: 800,
      stop_reason: 'tool_use',
    },
    tool_calls: [
      call({ id: 1 }),
      call({ id: 2, tool: 'create_replenishment_task', approval: 'rejected' }),
    ],
  },
]

// Two calls from one request, then one from another, newest first.
const calls = [
  call({ id: 3, tool: 'list_short_picks', model_call_id: 2, model_call_cost_usd: 0.012 }),
  call({ id: 2, tool: 'create_replenishment_task', approval: 'rejected' }),
  call({ id: 1 }),
]

const fetchMock = vi.fn(async (url: string) => {
  const path = new URL(url, 'http://x').pathname
  if (path === '/api/agent-log/summary') return new Response(JSON.stringify(summary))
  if (path === '/api/agent-log/sessions') return new Response(JSON.stringify(sessions))
  if (path === '/api/agent-log/sessions/abc12345def') return new Response(JSON.stringify(steps))
  return new Response(JSON.stringify(calls))
})

const requested = () => fetchMock.mock.calls.map(([url]) => url)

afterEach(() => {
  vi.unstubAllGlobals()
  fetchMock.mockClear()
})

describe('AgentLogPage', () => {
  it('shows the total cost at the top, with counts and a breakdown', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<AgentLogPage />)

    const totals = await screen.findByRole('region', { name: 'Totals' })
    expect(within(totals).getByLabelText('Total cost')).toHaveTextContent('$2.0183')
    expect(within(totals).getByText('Claude requests').nextSibling).toHaveTextContent('3')
    expect(within(totals).getByText('Tool calls').nextSibling).toHaveTextContent('5')
    expect(within(totals).getByText('Tokens in / out').nextSibling).toHaveTextContent(
      '1.00M / 300',
    )
    expect(within(totals).getByText('Investigator $2.0000')).toBeInTheDocument()
    expect(within(totals).getByText('claude-opus-5-5 $0.0183')).toBeInTheDocument()
  })

  it('lists sessions with their cost and opens one to show requests and tool calls', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<AgentLogPage />)

    const investigation = await screen.findByRole('button', { name: 'Investigation #7' })
    expect(within(investigation).getByText('$2.0000')).toBeInTheDocument()
    const chat = screen.getByRole('button', { name: 'Conversation abc12345' })
    expect(within(chat).getByText('1 rejected')).toBeInTheDocument()

    await userEvent.click(chat)

    const list = await screen.findByRole('list', { name: 'Steps' })
    expect(within(list).getByText('Claude request')).toBeInTheDocument()
    expect(within(list).getByText('$0.0060')).toBeInTheDocument() // once, not per tool call
    expect(within(list).getByText('Rejected')).toBeInTheDocument()
    expect(requested()).toContain('/api/agent-log/sessions/abc12345def')
  })

  it('shows a tool call\'s arguments and result when opened', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<AgentLogPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Conversation abc12345' }))
    const list = await screen.findByRole('list', { name: 'Steps' })

    await userEvent.click(within(list).getAllByRole('button', { name: /^find_stock/ })[0])

    expect(within(list).getByText(/"sku_code": "10442"/)).toBeInTheDocument()
    expect(within(list).getByText('3 results')).toBeInTheDocument()
  })

  it('has a flat list of all calls that counts each request\'s cost once', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<AgentLogPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'All calls' }))

    const list = await screen.findByRole('list', { name: 'Tool calls' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(3)
    expect(within(list).getByText('request $0.0120')).toBeInTheDocument()
    expect(within(list).getByText('request $0.0060')).toBeInTheDocument()
    expect(within(list).getByText('same request')).toBeInTheDocument()
  })

  it('sends the filters to the backend', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<AgentLogPage />)
    await screen.findByRole('button', { name: 'Investigation #7' })

    await userEvent.selectOptions(screen.getByLabelText('Source'), 'INVESTIGATOR')
    await userEvent.type(screen.getByLabelText('From'), '2026-06-01')
    await userEvent.click(screen.getByRole('button', { name: 'All calls' }))
    await userEvent.selectOptions(await screen.findByLabelText('Approval'), 'rejected')
    await userEvent.type(screen.getByLabelText('Tool'), 'find_stock')

    await vi.waitFor(() => {
      const rows = requested().filter((u) => !String(u).includes('/summary'))
      const last = new URL(String(rows.at(-1)), 'http://x')
      expect(last.pathname).toBe('/api/agent-log')
      expect(Object.fromEntries(last.searchParams)).toMatchObject({
        source: 'INVESTIGATOR',
        since: '2026-06-01T00:00:00',
        approval: 'rejected',
        tool: 'find_stock',
      })
    })
    // The totals follow the source and date range, not the tool or approval.
    const summaryUrl = requested().filter((u) => String(u).includes('/summary')).at(-1)
    expect(String(summaryUrl)).toContain('source=INVESTIGATOR')
    expect(String(summaryUrl)).not.toContain('tool=')
  })

  it('loads the next page of calls from the last id seen', async () => {
    const full = Array.from({ length: 50 }, (_, i) => call({ id: 100 - i, model_call_id: null }))
    const pager = vi.fn(async (url: string) => {
      const path = new URL(url, 'http://x').pathname
      if (path === '/api/agent-log/summary') return new Response(JSON.stringify(summary))
      if (path === '/api/agent-log/sessions') return new Response('[]')
      const before = new URL(url, 'http://x').searchParams.get('before_id')
      return new Response(JSON.stringify(before ? [call({ id: 50, tool: 'last_one' })] : full))
    })
    vi.stubGlobal('fetch', pager)
    render(<AgentLogPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'All calls' }))

    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(await screen.findByRole('button', { name: /^last_one/ })).toBeInTheDocument()
    expect(pager.mock.calls.at(-1)?.[0]).toContain('before_id=51')
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('says so when nothing is logged', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        new Response(
          JSON.stringify(
            url.includes('/summary')
              ? { ...summary, total_cost_usd: 0, model_calls: 0, tool_calls: 0, sessions: 0 }
              : [],
          ),
        ),
      ),
    )
    render(<AgentLogPage />)

    expect(await screen.findByText(/Nothing logged yet/)).toBeInTheDocument()
    expect(screen.getByLabelText('Total cost')).toHaveTextContent('$0.0000')
  })

  it('reports a load failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'boom' }), { status: 500 })),
    )
    render(<AgentLogPage />)

    expect(await screen.findByText(/Couldn't load the agent log: boom/)).toBeInTheDocument()
  })
})
