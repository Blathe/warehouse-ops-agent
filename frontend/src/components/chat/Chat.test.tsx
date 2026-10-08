import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AgentTurn } from '@/lib/api'
import { Chat } from './Chat'

function turn(overrides: Partial<AgentTurn>): AgentTurn {
  return {
    conversation_id: 'conv_1',
    model: 'claude-opus-5-5',
    status: 'done',
    reply: '',
    pending: [],
    tool_calls: [],
    ...overrides,
  }
}

// Answers for the read-only lookups the chat makes on the side (conversation cost, stock levels),
// by URL. Anything else not listed is a 404, so these never use up a scripted chat response.
let sideRoutes: Record<string, unknown> = {}

// Replaces window.fetch with scripted JSON responses and records the requests.
function mockFetch(...responses: Array<{ status?: number; body: unknown }>) {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.startsWith('/api/agent-log') || url.startsWith('/api/floor-map')) {
      return url in sideRoutes
        ? new Response(JSON.stringify(sideRoutes[url]))
        : new Response('{}', { status: 404 })
    }
    const next = responses.shift()
    if (!next) throw new Error('unexpected fetch')
    return new Response(JSON.stringify(next.body), { status: next.status ?? 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function requestBody(fetchMock: ReturnType<typeof mockFetch>, call: number): unknown {
  return JSON.parse(fetchMock.mock.calls[call][1]?.body as string)
}

const pendingMove = {
  tool_use_id: 'tu_1',
  tool: 'create_replenishment_task',
  input: {
    sku_code: '58368',
    from_location: 'A-03-06-2',
    to_location: 'A-03-04-1',
    qty: 144,
    reason: 'empty',
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
  sideRoutes = {}
})

describe('Chat', () => {
  it('renders the assistant reply as markdown but leaves what you typed alone', async () => {
    mockFetch({
      body: turn({
        reply: ['**2 faces** need stock:', '', '| Face | Qty |', '|---|---|', '| A-03-04-1 | 144 |'].join(
          '\n',
        ),
      }),
    })
    render(<Chat supervisor="Pat" model={null} />)

    await userEvent.type(screen.getByLabelText('Message'), 'Show **me** the faces{Enter}')

    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'A-03-04-1' })).toBeInTheDocument()
    expect(screen.getByText('2 faces').tagName).toBe('STRONG')
    // The supervisor's own message stays literal text.
    expect(screen.getByText('Show **me** the faces')).toBeInTheDocument()
  })

  it('sends a message and shows the reply with its tool calls', async () => {
    const fetchMock = mockFetch({
      body: turn({
        reply: '13 faces need stock.',
        tool_calls: [
          {
            tool: 'list_replenishment_needs',
            input: {},
            ok: true,
            summary: '13 results',
            approval: 'n/a',
          },
        ],
      }),
    })
    render(<Chat supervisor="Pat" model={null} />)

    await userEvent.type(screen.getByLabelText('Message'), 'What needs replenishing?{Enter}')

    expect(await screen.findByText('13 faces need stock.')).toBeInTheDocument()
    expect(screen.getByText('What needs replenishing?')).toBeInTheDocument()
    expect(screen.getByText('1 tool call')).toBeInTheDocument()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/chat')
    expect(requestBody(fetchMock, 0)).toEqual({
      message: 'What needs replenishing?',
      conversation_id: null,
      model: null,
    })
  })

  it('asks for approval, then sends the decision with the supervisor name', async () => {
    const fetchMock = mockFetch(
      { body: turn({ status: 'needs_approval', reply: 'Refilling A-03-04-1.', pending: [pendingMove] }) },
      { body: turn({ reply: 'Task #18 is approved.' }) },
    )
    render(<Chat supervisor="Pat" model={null} />)

    await userEvent.type(screen.getByLabelText('Message'), 'Refill it{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))

    expect(await screen.findByText('Task #18 is approved.')).toBeInTheDocument()
    expect(screen.getByText('claude-opus-5-5 · Approved by Pat')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    const approval = fetchMock.mock.calls.findIndex(
      ([url]) => url === '/api/conversations/conv_1/approval',
    )
    expect(approval).toBeGreaterThan(0)
    expect(requestBody(fetchMock, approval)).toEqual({ approve: true, decided_by: 'Pat' })
  })

  it('blocks new messages while a task is waiting for approval', async () => {
    mockFetch({ body: turn({ status: 'needs_approval', pending: [pendingMove] }) })
    render(<Chat supervisor="Pat" model={null} />)
    await userEvent.type(screen.getByLabelText('Message'), 'Refill it{Enter}')
    await screen.findByRole('button', { name: 'Approve' })
    expect(screen.getByLabelText('Message')).toBeDisabled()
  })

  it('shows API errors', async () => {
    mockFetch({ status: 502, body: { detail: 'Could not reach the Claude API' } })
    render(<Chat supervisor="Pat" model={null} />)
    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')
    expect(await screen.findByText('Could not reach the Claude API')).toBeInTheDocument()
  })

  it('shows the model, this chat’s running cost and starts a new chat', async () => {
    sideRoutes['/api/agent-log/sessions/conv_1'] = [
      { model_call: { cost_usd: 0.0123 }, tool_calls: [] },
      { model_call: { cost_usd: 0.0200 }, tool_calls: [] },
    ]
    mockFetch({ body: turn({ reply: 'Hello there.' }) })
    render(<Chat supervisor="Pat" model="claude-haiku-4-5" modelLabels={{ 'claude-haiku-4-5': 'Claude Haiku 4.5' }} />)
    expect(screen.getByText('Claude Haiku 4.5')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New chat' })).toBeDisabled()

    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')

    expect(await screen.findByText('$0.0323 this chat')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
    expect(screen.queryByText('Hello there.')).not.toBeInTheDocument()
    expect(screen.queryByText(/this chat/)).not.toBeInTheDocument()
  })

  it('starts a fresh conversation after New chat', async () => {
    const fetchMock = mockFetch({ body: turn({ reply: 'One.' }) }, { body: turn({ conversation_id: 'conv_2', reply: 'Two.' }) })
    render(<Chat supervisor="Pat" model={null} />)
    await userEvent.type(screen.getByLabelText('Message'), 'first{Enter}')
    await screen.findByText('One.')

    await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
    await userEvent.type(screen.getByLabelText('Message'), 'second{Enter}')

    expect(await screen.findByText('Two.')).toBeInTheDocument()
    const chatCalls = fetchMock.mock.calls.filter(([url]) => url === '/api/chat')
    expect(JSON.parse(chatCalls[1][1]?.body as string).conversation_id).toBeNull()
  })

  it('marks who said what with an avatar', async () => {
    mockFetch({ body: turn({ reply: 'Hi Pat.' }) })
    render(<Chat supervisor="pat" model={null} />)
    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')
    await screen.findByText('Hi Pat.')
    expect(screen.getByText('P')).toBeInTheDocument() // the supervisor's initial
  })
})
