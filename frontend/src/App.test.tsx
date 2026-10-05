import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const models = {
  default: 'claude-opus-5-5',
  models: [
    { id: 'claude-opus-5-5', label: 'Claude Opus 5.5', input_per_mtok: 4, output_per_mtok: 20 },
    { id: 'claude-haiku-4-5', label: 'Claude Haiku 4.5', input_per_mtok: 1, output_per_mtok: 5 },
  ],
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200 })
}

const floorMap = {
  bays: ['A-03-04-1', 'A-03-06-1'].map((location, i) => ({
    zone: 'A',
    aisle: 3,
    bay: 4 + 2 * i,
    x: 9,
    y: 4 + 2 * i,
    pick: {
      location,
      sku_code: '58368',
      description: 'Hollow Pine Circle Hook 2/0 25pk',
      on_hand: 0,
      min_qty: 36,
      max_qty: 144,
      status: 'empty',
      open_task_id: null,
    },
    reserve: [],
    open_discrepancies: [],
  })),
  staging: [],
  counts: { ok: 0, low: 0, empty: 2, unassigned: 0 },
}

let chatReply: unknown

const activeTasks = [
  {
    task_id: 17,
    status: 'APPROVED',
    sku_code: '58368',
    description: 'Hollow Pine Circle Hook 2/0 25pk',
    from_location: 'A-03-06-2',
    to_location: 'A-03-06-1',
    lpn: 'LPN98259272',
    qty: 144,
    reason: 'Pick face empty',
    created_by: 'agent',
    created_at: '2026-06-01T12:48:00',
    approved_by: 'Pat',
    decided_at: '2026-06-01T12:49:00',
  },
]

// What the next simulation ticks answer (a Response is returned as is); empty means "nothing waiting".
let tickReplies: unknown[] = []

const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
  if (url === '/api/models') return json(models)
  if (url === '/api/floor-map') return json(floorMap)
  if (url.startsWith('/api/tasks')) return json(activeTasks)
  if (url.startsWith('/api/cycle-counts')) return json([])
  if (url === '/api/simulation/tick') {
    const next = tickReplies.shift()
    return next instanceof Response ? next : json(next ?? { completed: null })
  }
  return json(chatReply)
})

beforeEach(() => {
  tickReplies = []
  chatReply = {
    conversation_id: 'conv_1',
    model: 'claude-haiku-4-5',
    status: 'done',
    reply: 'Cheap answer.',
    pending: [],
    tool_calls: [],
  }
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  localStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe('App model picker', () => {
  it('defaults to the backend default and lists prices', async () => {
    render(<App />)
    const picker = await screen.findByLabelText('Model')
    expect(picker).toHaveValue('claude-opus-5-5')
    expect(within(picker).getByText('Claude Haiku 4.5 ($1 / $5 per M tokens)')).toBeInTheDocument()
  })

  it('sends the chosen model, remembers it and labels the reply', async () => {
    render(<App />)
    await userEvent.selectOptions(await screen.findByLabelText('Model'), 'claude-haiku-4-5')
    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')

    expect(await screen.findByText('Cheap answer.')).toBeInTheDocument()
    expect(screen.getByText('Claude Haiku 4.5')).toBeInTheDocument()
    const chatCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat')
    expect(JSON.parse(chatCall?.[1]?.body as string).model).toBe('claude-haiku-4-5')
    expect(localStorage.getItem('warehouse-ops.model')).toBe('claude-haiku-4-5')
  })

  it('restores a remembered model', async () => {
    localStorage.setItem('warehouse-ops.model', 'claude-haiku-4-5')
    render(<App />)
    expect(await screen.findByLabelText('Model')).toHaveValue('claude-haiku-4-5')
  })
})

describe('App two-column layout', () => {
  it('shows the chat, floor map and activity together', async () => {
    render(<App />)
    expect(screen.getByRole('region', { name: 'Chat' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Floor map' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Agent activity' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^A-03-04-1/ })).toBeInTheDocument()
  })

  it('logs the agent turn and points the map at the bay being replenished', async () => {
    chatReply = {
      conversation_id: 'conv_1',
      model: 'claude-opus-5-5',
      status: 'needs_approval',
      reply: 'Refilling A-03-04-1.',
      tool_calls: [
        { tool: 'list_replenishment_needs', input: {}, ok: true, summary: '13 results', approval: 'n/a' },
      ],
      pending: [
        {
          tool_use_id: 't1',
          tool: 'create_replenishment_task',
          input: { sku_code: '58368', from_location: 'A-03-06-2', to_location: 'A-03-04-1', qty: 144, reason: 'empty' },
        },
      ],
    }
    render(<App />)
    await userEvent.type(screen.getByLabelText('Message'), 'Refill it{Enter}')

    const activity = await screen.findByRole('list', { name: 'Agent activity' })
    expect(within(activity).getByText('Waiting for your approval')).toBeInTheDocument()
    expect(within(activity).getByText('Checked replenishment needs')).toBeInTheDocument()
    // The destination bay is selected and its details are shown.
    expect(await screen.findByRole('button', { name: /^A-03-04-1/, pressed: true })).toBeInTheDocument()
    // The map reloads after the turn.
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/floor-map').length).toBeGreaterThan(1)
  })
})

describe('App tasks page', () => {
  it('shows the number of active tasks on the Tasks tab', async () => {
    render(<App />)
    expect(await screen.findByLabelText('1 active')).toBeInTheDocument()
  })

  it('opens the tasks page and keeps the chat when going back', async () => {
    render(<App />)
    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')
    expect(await screen.findByText('Cheap answer.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^Tasks/ }))
    expect(await screen.findByRole('heading', { name: 'Replenishment tasks' })).toBeInTheDocument()
    expect(await screen.findByRole('listitem', { name: 'Task #17' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Workspace' }))
    expect(screen.getByText('Cheap answer.')).toBeInTheDocument()
  })

  it('shows a task on the map and returns to the workspace', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /^Tasks/ }))
    const card = await screen.findByRole('listitem', { name: 'Task #17' })

    await userEvent.click(within(card).getByRole('button', { name: 'Show on map' }))

    expect(screen.queryByRole('heading', { name: 'Replenishment tasks' })).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^A-03-06-1/, pressed: true })).toBeInTheDocument()
  })
})

describe('App agent activity', () => {
  it('has nothing to clear until the agent has done something', () => {
    render(<App />)
    expect(screen.queryByRole('button', { name: 'Clear agent activity' })).not.toBeInTheDocument()
  })

  it('clears the activity feed', async () => {
    chatReply = {
      conversation_id: 'conv_1',
      model: 'claude-opus-5-5',
      status: 'done',
      reply: 'Two faces need stock.',
      pending: [],
      tool_calls: [
        { tool: 'list_replenishment_needs', input: {}, ok: true, summary: '13 results', approval: 'n/a' },
      ],
    }
    render(<App />)
    await userEvent.type(screen.getByLabelText('Message'), 'What needs stock?{Enter}')
    const activity = await screen.findByRole('list', { name: 'Agent activity' })
    expect(within(activity).getByText('Checked replenishment needs')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Clear agent activity' }))

    expect(screen.queryByRole('list', { name: 'Agent activity' })).not.toBeInTheDocument()
    expect(screen.getByText('Tool calls and approvals will show up here as you chat.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear agent activity' })).not.toBeInTheDocument()
    expect(screen.getByText('Two faces need stock.')).toBeInTheDocument() // the chat is untouched
  })
})

describe('App crew simulation', () => {
  const ticks = () => fetchMock.mock.calls.filter(([url]) => url === '/api/simulation/tick').length

  afterEach(() => vi.useRealTimers())

  it('does nothing until it is switched on', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<App />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000)
    })

    expect(ticks()).toBe(0)
    expect(screen.getByRole('button', { name: /Simulate crew/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('finishes a task every 5 seconds while on, and stops when switched off', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    tickReplies = [{ completed: { ...activeTasks[0], status: 'DONE' } }]
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<App />)
    const toggle = screen.getByRole('button', { name: /Simulate crew/ })

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(ticks()).toBe(0) // the first tick comes after the first 5 seconds
    const mapLoadsBefore = fetchMock.mock.calls.filter(([url]) => url === '/api/floor-map').length

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    expect(ticks()).toBe(1)
    const activity = await screen.findByRole('list', { name: 'Agent activity' })
    expect(within(activity).getByText('Crew completed task #17')).toBeInTheDocument()
    // The map reloads so the finished move shows up.
    const mapLoadsAfter = fetchMock.mock.calls.filter(([url]) => url === '/api/floor-map').length
    expect(mapLoadsAfter).toBeGreaterThan(mapLoadsBefore)

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000)
    })
    expect(ticks()).toBe(1) // switched off, so no more ticks
  })

  it('keeps ticking when nothing is waiting, without adding activity', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<App />)
    await user.click(screen.getByRole('button', { name: /Simulate crew/ }))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })

    expect(ticks()).toBe(2)
    expect(screen.queryByRole('list', { name: 'Agent activity' })).not.toBeInTheDocument()
  })

  it('switches off and says why when the backend refuses a tick', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    tickReplies = [
      new Response(JSON.stringify({ detail: 'Task #17: the source pallet no longer holds 144' }), {
        status: 409,
      }),
    ]
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<App />)
    const toggle = screen.getByRole('button', { name: /Simulate crew/ })
    await user.click(toggle)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    const activity = await screen.findByRole('list', { name: 'Agent activity' })
    expect(within(activity).getByText('Crew simulation stopped')).toBeInTheDocument()
    expect(within(activity).getByText(/source pallet no longer holds 144/)).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
  })
})
