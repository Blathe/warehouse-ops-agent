import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'

import App from './App'

// The app reads its page from the URL; tests start on the workspace unless told otherwise.
function renderApp(path = '/workspace'): ReturnType<typeof render> {
  const ui: ReactElement = (
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  )
  return render(ui)
}

// The model, supervisor name and crew simulation live in the settings popover.
async function openSettings(user: ReturnType<typeof userEvent.setup> = userEvent.setup()) {
  await user.click(screen.getByRole('button', { name: 'Settings' }))
}

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

const overview = {
  as_of: '2026-06-01T13:00:00',
  empty_faces: 0,
  low_faces: 0,
  short_picks_24h: 0,
  tasks_awaiting_approval: 0,
  tasks_approved: 0,
  open_discrepancies: 0,
  zones: [],
  short_picks_by_hour: [],
  urgent_needs: [],
}

const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
  if (url === '/api/models') return json(models)
  if (url === '/api/floor-map') return json(floorMap)
  if (url === '/api/overview') return json(overview)
  if (url.startsWith('/api/tasks')) return json(activeTasks)
  if (url.startsWith('/api/cycle-counts')) return json([])
  if (url === '/api/simulation/tick') {
    const next = tickReplies.shift()
    return next instanceof Response ? next : json(next ?? { completed: null })
  }
  // The chat and approval endpoints stream server-sent events: one `turn` event with the result.
  if (url.endsWith('/stream')) {
    return new Response(`event: turn\ndata: ${JSON.stringify(chatReply)}\n\n`)
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
    renderApp()
    await openSettings()
    const picker = await screen.findByLabelText('Model')
    expect(picker).toHaveValue('claude-opus-5-5')
    expect(within(picker).getByText('Claude Haiku 4.5 ($1 / $5 per M tokens)')).toBeInTheDocument()
  })

  it('sends the chosen model, remembers it and labels the reply', async () => {
    renderApp()
    await openSettings()
    await userEvent.selectOptions(await screen.findByLabelText('Model'), 'claude-haiku-4-5')
    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')

    expect(await screen.findByText('Cheap answer.')).toBeInTheDocument()
    expect(
      screen.getByText('Claude Haiku 4.5', { selector: '[data-slot="message-footer"]' }),
    ).toBeInTheDocument()
    const chatCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat/stream')
    expect(JSON.parse(chatCall?.[1]?.body as string).model).toBe('claude-haiku-4-5')
    expect(localStorage.getItem('warehouse-ops.model')).toBe('claude-haiku-4-5')
  })

  it('restores a remembered model', async () => {
    localStorage.setItem('warehouse-ops.model', 'claude-haiku-4-5')
    renderApp()
    await openSettings()
    expect(await screen.findByLabelText('Model')).toHaveValue('claude-haiku-4-5')
  })
})

describe('App workspace', () => {
  it('shows the chat and the agent activity side by side', async () => {
    renderApp()
    expect(screen.getByRole('region', { name: 'Chat' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Agent activity' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Floor map' })).not.toBeInTheDocument()
  })

  it('logs the agent turn and offers to show the bay being replenished on the floor map', async () => {
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
    renderApp()
    await userEvent.type(screen.getByLabelText('Message'), 'Refill it{Enter}')

    const activity = await screen.findByRole('list', { name: 'Agent activity' })
    expect(within(activity).getByText('Waiting for your approval')).toBeInTheDocument()
    expect(within(activity).getByText('Checked replenishment needs')).toBeInTheDocument()

    // The destination bay is selected and highlighted on the floor map page.
    await userEvent.click(screen.getByRole('button', { name: 'Show A-03-04-1 on the floor map' }))
    expect(await screen.findByRole('heading', { name: 'Floor map', level: 1 })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^A-03-04-1/, pressed: true })).toBeInTheDocument()
  })
})

describe('App floor map page', () => {
  it('opens from its URL and shows the map with the zone filter', async () => {
    renderApp('/floor-map')
    expect(await screen.findByRole('heading', { name: 'Floor map', level: 1 })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^A-03-04-1/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All zones' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('reloads the map after an agent turn', async () => {
    renderApp()
    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')
    await screen.findByText('Cheap answer.')
    await userEvent.click(screen.getByRole('link', { name: 'Floor map' }))
    await screen.findByRole('button', { name: /^A-03-04-1/ })
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/floor-map').length).toBeGreaterThanOrEqual(1)
  })
})

describe('App tasks page', () => {
  it('shows the number of active tasks on the Tasks tab', async () => {
    renderApp()
    expect(await screen.findByLabelText('1 active')).toBeInTheDocument()
  })

  it('opens the tasks page and keeps the chat when going back', async () => {
    renderApp()
    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')
    expect(await screen.findByText('Cheap answer.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: /^Tasks/ }))
    expect(await screen.findByRole('heading', { name: 'Replenishment tasks' })).toBeInTheDocument()
    expect(await screen.findByRole('listitem', { name: 'Task #17' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: 'Chat' }))
    expect(screen.getByText('Cheap answer.')).toBeInTheDocument()
  })

  it('shows a task on the floor map page', async () => {
    renderApp()
    await userEvent.click(screen.getByRole('link', { name: /^Tasks/ }))
    const card = await screen.findByRole('listitem', { name: 'Task #17' })

    await userEvent.click(within(card).getByRole('button', { name: 'Show on map' }))

    expect(screen.queryByRole('heading', { name: 'Replenishment tasks' })).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Floor map', level: 1 })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^A-03-06-1/, pressed: true })).toBeInTheDocument()
  })
})

describe('App agent activity', () => {
  it('has nothing to clear until the agent has done something', () => {
    renderApp()
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
    renderApp()
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
    renderApp()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000)
    })

    expect(ticks()).toBe(0)
    await openSettings()
    expect(screen.getByRole('button', { name: /Simulate crew/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('finishes a task every 5 seconds while on, and stops when switched off', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    tickReplies = [{ completed: { ...activeTasks[0], status: 'DONE' } }]
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp('/floor-map') // the map is on show, so it should reload when a task finishes
    await openSettings(user)
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
    // ...and a toast tells the supervisor whichever page they are on.
    const toasts = screen.getByRole('region', { name: /Notifications/ })
    expect(await within(toasts).findByText('Crew completed task #17')).toBeInTheDocument()
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
    renderApp()
    await openSettings(user)
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
    renderApp()
    await openSettings(user)
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

describe('App routing', () => {
  it('opens the overview from the root URL', async () => {
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('data-active', 'true')
  })

  it('opens a page straight from its URL', async () => {
    renderApp('/counts')
    expect(await screen.findByRole('heading', { name: 'Cycle counts', level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Simulate cycle count' })).toBeInTheDocument()
  })

  it('sends unknown URLs to the overview', async () => {
    renderApp('/nope')
    expect(await screen.findByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument()
  })
})

describe('App notifications', () => {
  it('nudges the supervisor when the agent needs approval and they are on another page', async () => {
    chatReply = {
      conversation_id: 'conv_1',
      model: 'claude-opus-5-5',
      status: 'needs_approval',
      reply: 'Refilling A-03-04-1.',
      tool_calls: [],
      pending: [
        {
          tool_use_id: 't1',
          tool: 'create_replenishment_task',
          input: { sku_code: '58368', from_location: 'A-03-06-2', to_location: 'A-03-04-1', qty: 144, reason: 'empty' },
        },
      ],
    }
    renderApp('/floor-map') // the chat stays mounted behind whatever page is showing
    await userEvent.type(screen.getByLabelText('Message'), 'Refill it{Enter}')

    const toasts = screen.getByRole('region', { name: /Notifications/ })
    expect(await within(toasts).findByText('The agent needs your approval')).toBeInTheDocument()
    await userEvent.click(within(toasts).getByRole('button', { name: 'Review' }))
    expect(await screen.findByRole('heading', { name: 'Chat', level: 1 })).toBeInTheDocument()
  })

  it('stays quiet about an approval request while the supervisor is in the workspace', async () => {
    chatReply = {
      conversation_id: 'conv_1',
      model: 'claude-opus-5-5',
      status: 'needs_approval',
      reply: 'Refilling.',
      tool_calls: [],
      pending: [
        {
          tool_use_id: 't1',
          tool: 'create_replenishment_task',
          input: { sku_code: '58368', from_location: 'A-03-06-2', to_location: 'A-03-04-1', qty: 144, reason: 'empty' },
        },
      ],
    }
    renderApp()
    await userEvent.type(screen.getByLabelText('Message'), 'Refill it{Enter}')
    await screen.findByRole('button', { name: 'Approve' })

    expect(screen.queryByText('The agent needs your approval')).not.toBeInTheDocument()
  })
})

describe('App command palette', () => {
  it('opens with Ctrl+K and jumps to a page', async () => {
    renderApp()
    await userEvent.keyboard('{Control>}k{/Control}')

    await userEvent.type(await screen.findByPlaceholderText(/Go to a page/), 'cycle')
    await userEvent.click(screen.getByRole('option', { name: 'Cycle counts' }))

    expect(await screen.findByRole('heading', { name: 'Cycle counts', level: 1 })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Go to a page/)).not.toBeInTheDocument()
  })

  it('finds a pick face by SKU and shows it on the floor map', async () => {
    renderApp()
    await userEvent.click(screen.getByRole('button', { name: 'Open the command palette' }))

    await userEvent.type(await screen.findByPlaceholderText(/Go to a page/), '58368')
    await userEvent.click(await screen.findByRole('option', { name: /A-03-06-1/ }))

    expect(await screen.findByRole('heading', { name: 'Floor map', level: 1 })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^A-03-06-1/, pressed: true })).toBeInTheDocument()
  })

  it('switches the theme and the crew simulation', async () => {
    renderApp()
    await userEvent.keyboard('{Control>}k{/Control}')
    await userEvent.click(await screen.findByRole('option', { name: 'Switch to dark mode' }))
    expect(document.documentElement).toHaveClass('dark')
    expect(screen.getByRole('button', { name: 'Switch to light mode' })).toBeInTheDocument()

    await userEvent.keyboard('{Control>}k{/Control}')
    await userEvent.click(await screen.findByRole('option', { name: 'Start the crew simulation' }))
    // The header shows the crew is running, and the settings toggle agrees.
    expect(screen.getByRole('button', { name: 'Stop the crew simulation' })).toBeInTheDocument()
    await openSettings()
    expect(screen.getByRole('button', { name: /Simulate crew/ })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('App settings menu', () => {
  it('keeps the supervisor name in the sidebar and remembers it', async () => {
    renderApp()
    const settings = screen.getByRole('button', { name: 'Settings' })
    expect(settings).toHaveTextContent('Supervisor')

    await openSettings()
    const name = screen.getByLabelText('Supervisor name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Pat')
    await userEvent.tab() // leaving the field saves it

    expect(settings).toHaveTextContent('Pat')
    expect(localStorage.getItem('warehouse-ops.supervisor')).toBe('Pat')
  })

  it('stops the crew from the header', async () => {
    renderApp()
    await openSettings()
    await userEvent.click(screen.getByRole('button', { name: /Simulate crew/ }))

    await userEvent.click(screen.getByRole('button', { name: 'Stop the crew simulation' }))

    expect(screen.queryByRole('button', { name: 'Stop the crew simulation' })).not.toBeInTheDocument()
    await openSettings() // clicking outside closed the popover
    expect(screen.getByRole('button', { name: /Simulate crew/ })).toHaveAttribute('aria-pressed', 'false')
  })
})
