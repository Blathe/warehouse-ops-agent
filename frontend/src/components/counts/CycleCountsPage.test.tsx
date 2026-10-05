import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { CycleCount, Investigation } from '@/lib/api'
import { CycleCountsPage } from './CycleCountsPage'

function count(overrides: Partial<CycleCount> = {}): CycleCount {
  return {
    id: 4,
    location: 'A-02-23-1',
    sku_code: '98781',
    description: 'Ridgeline Crankbait 3/8oz Perch',
    case_qty: 12,
    lpn: null,
    counted_by: 'Kim Lee',
    counted_at: '2026-06-01T13:00:00',
    system_qty: 33,
    counted_qty: 3,
    variance: -30,
    status: 'DISCREPANCY',
    resolved_by: null,
    resolved_at: null,
    resolution_reason: null,
    investigation: null,
    ...overrides,
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// Routes each request to a handler; records every call.
function mockApi(routes: Record<string, (init?: RequestInit) => Response>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const route = Object.keys(routes).find((prefix) => url.startsWith(prefix))
    if (!route) throw new Error(`unexpected fetch ${url}`)
    return routes[route](init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function bodyOf(fetchMock: ReturnType<typeof mockApi>, url: string): unknown {
  const call = fetchMock.mock.calls.find(([u]) => u === url)
  return JSON.parse(call?.[1]?.body as string)
}

afterEach(() => vi.unstubAllGlobals())

describe('CycleCountsPage', () => {
  it('lists open discrepancies with system vs counted', async () => {
    mockApi({ '/api/cycle-counts': () => json([count()]) })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={() => {}} />)

    const card = await screen.findByRole('listitem', { name: 'Count at A-02-23-1' })
    expect(within(card).getByText('Discrepancy')).toBeInTheDocument()
    expect(within(card).getByText('−30')).toBeInTheDocument()
    expect(card).toHaveTextContent('System 33 · Counted 3')
  })

  it('runs a simulated count and reports what it found', async () => {
    const onChange = vi.fn()
    const run = { counted: 30, matched: 22, discrepancies: Array.from({ length: 8 }, (_, i) => count({ id: i })) }
    mockApi({
      '/api/simulation/cycle-count': () => json(run),
      '/api/cycle-counts': () => json([]),
    })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={() => {}} onChange={onChange} countDurationMs={0} />)

    await userEvent.click(screen.getByRole('button', { name: 'Simulate cycle count' }))

    expect(await screen.findByText(/Counted 30 locations/)).toHaveTextContent(
      'Counted 30 locations: 22 matched, 8 discrepancies opened. The AI is investigating each one.',
    )
    expect(onChange).toHaveBeenCalledWith({ kind: 'counted', run })
  })

  it('needs a reason before accepting, then sends it with the supervisor', async () => {
    const onChange = vi.fn()
    const accepted = count({ status: 'ACCEPTED', resolved_by: 'Pat', resolution_reason: 'Bad adjustment' })
    const fetchMock = mockApi({
      '/api/cycle-counts/4/accept': () => json(accepted),
      '/api/cycle-counts': () => json([count()]),
    })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={() => {}} onChange={onChange} countDurationMs={0} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Accept count' }))
    const confirm = screen.getByRole('button', { name: 'Adjust system to 3' })
    expect(confirm).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reason for accepting'), 'Bad adjustment')
    await userEvent.click(confirm)

    await vi.waitFor(() => expect(onChange).toHaveBeenCalledWith({ kind: 'accepted', count: accepted }))
    expect(bodyOf(fetchMock, '/api/cycle-counts/4/accept')).toEqual({
      decided_by: 'Pat',
      reason: 'Bad adjustment',
    })
  })

  it('asks for a recount and shows errors from the server', async () => {
    mockApi({
      '/api/cycle-counts/4/recount': () => json({ detail: 'Count #4 is ACCEPTED, not an open discrepancy' }, 409),
      '/api/cycle-counts': () => json([count()]),
    })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={() => {}} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Recount' }))

    expect(await screen.findByText('Count #4 is ACCEPTED, not an open discrepancy')).toBeInTheDocument()
  })

  it('shows a reserve slot on the map by its bay', async () => {
    const onShowOnMap = vi.fn()
    mockApi({ '/api/cycle-counts': () => json([count({ location: 'A-04-21-3', lpn: 'LPN27187635' })]) })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={onShowOnMap} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Show on map' }))

    expect(onShowOnMap).toHaveBeenCalledWith('A-04-21-1')
  })
})

function investigation(overrides: Partial<Investigation> = {}): Investigation {
  return {
    id: 1,
    status: 'DONE',
    model: 'claude-sonnet-5-5',
    summary: 'A +30 adjustment with no reason was keyed here.',
    causes: [
      {
        cause: 'Mistaken manual adjustment',
        likelihood: 'high',
        evidence: ['May 30 18:39: ADJUSTMENT +30 by Michael Mcguire, no reason'],
      },
    ],
    next_steps: ['Ask Michael Mcguire about the adjustment'],
    error: null,
    tool_calls: 3,
    started_at: '2026-06-01T13:00:00',
    finished_at: '2026-06-01T13:00:30',
    ...overrides,
  }
}

describe('CycleCountsPage investigations', () => {
  it('shows a progress bar while the clerk counts', async () => {
    mockApi({
      '/api/simulation/cycle-count': () => json({ counted: 30, matched: 30, discrepancies: [] }),
      '/api/cycle-counts': () => json([]),
    })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={() => {}} countDurationMs={300} />)

    await userEvent.click(screen.getByRole('button', { name: 'Simulate cycle count' }))

    expect(screen.getByRole('button', { name: 'Counting...' })).toBeDisabled()
    expect(screen.getByRole('status', { name: 'Cycle count in progress' })).toHaveTextContent(/Counting [ABC]-\d{2}-\d{2}-\d/)
    expect(await screen.findByText(/30 matched, 0 discrepancies/)).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Cycle count in progress' })).not.toBeInTheDocument()
  })

  it('shows the causes, evidence and next steps', async () => {
    mockApi({ '/api/cycle-counts': () => json([count({ investigation: investigation() })]) })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={() => {}} />)

    expect(await screen.findByText('A +30 adjustment with no reason was keyed here.')).toBeInTheDocument()
    const causes = screen.getByRole('list', { name: 'Likely causes' })
    expect(within(causes).getByText('Likely')).toBeInTheDocument()
    expect(within(causes).getByText('Mistaken manual adjustment')).toBeInTheDocument()
    expect(within(causes).getByText(/ADJUSTMENT \+30 by Michael Mcguire/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Next steps' })).toHaveTextContent('Ask Michael Mcguire')
    expect(screen.getByText('claude-sonnet-5-5 · 3 lookups')).toBeInTheDocument()
  })

  it('checks back until a running investigation finishes', async () => {
    const onChange = vi.fn()
    const replies = [
      [count({ investigation: investigation({ status: 'RUNNING', summary: null }) })],
      [count({ investigation: investigation() })],
    ]
    mockApi({ '/api/cycle-counts': () => json(replies.length > 1 ? replies.shift() : replies[0]) })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={() => {}} onChange={onChange} pollMs={10} />)

    expect(await screen.findByText('AI is investigating this discrepancy...')).toBeInTheDocument()
    expect(await screen.findByText('A +30 adjustment with no reason was keyed here.')).toBeInTheDocument()
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ kind: 'investigated' }))
  })

  it('can run a failed investigation again', async () => {
    const failed = count({ investigation: investigation({ status: 'FAILED', error: 'Claude API error (401)' }) })
    const fetchMock = mockApi({
      '/api/cycle-counts/4/investigate': () => json(count({ investigation: investigation({ status: 'RUNNING' }) })),
      '/api/cycle-counts': () => json([failed]),
    })
    render(<CycleCountsPage supervisor="Pat" onShowOnMap={() => {}} />)

    expect(await screen.findByText('Investigation failed: Claude API error (401)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === '/api/cycle-counts/4/investigate')).toBe(true),
    )
  })
})
