import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ReplenishmentTask } from '@/lib/api'
import { TasksPage } from './TasksPage'

function task(overrides: Partial<ReplenishmentTask> = {}): ReplenishmentTask {
  return {
    task_id: 17,
    status: 'APPROVED',
    sku_code: '13390',
    description: 'Northfork Wading Boots Size 12',
    from_location: 'C-01-02-2',
    to_location: 'C-01-01-1',
    lpn: 'LPN47810021',
    qty: 30,
    reason: 'Pick face empty',
    created_by: 'agent',
    created_at: '2026-06-01T12:48:00',
    approved_by: 'Pat',
    decided_at: '2026-06-01T12:49:00',
    ...overrides,
  }
}

const active = [
  task(),
  task({
    task_id: 18,
    status: 'PROPOSED',
    sku_code: '94659',
    description: 'Bluegill Bay Offset Worm Hook #2 25pk',
    from_location: 'A-03-10-2',
    to_location: 'A-03-08-1',
    qty: 240,
    approved_by: null,
    decided_at: null,
  }),
]

const fetchMock = vi.fn(async (url: string) => {
  const filter = new URL(url, 'http://x').searchParams.get('status')
  const body =
    filter === 'active'
      ? active
      : filter === 'done'
        ? [task({ task_id: 9, status: 'DONE' })]
        : []
  return new Response(JSON.stringify(body))
})

// The URLs that were requested, in order.
const requested = () => fetchMock.mock.calls.map(([url]) => url)

afterEach(() => {
  vi.unstubAllGlobals()
  fetchMock.mockClear()
})

describe('TasksPage', () => {
  it('lists the active tasks with their move, status and who approved them', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<TasksPage onShowOnMap={() => {}} />)

    const first = await screen.findByRole('listitem', { name: 'Task #17' })
    expect(within(first).getByText('Approved')).toBeInTheDocument()
    expect(within(first).getByText('Zone C')).toBeInTheDocument()
    expect(within(first).getByText('SKU 13390')).toBeInTheDocument()
    expect(within(first).getByText('Move 30')).toBeInTheDocument()
    expect(within(first).getByText(/C-01-02-2/)).toBeInTheDocument()
    expect(within(first).getByText(/Approved by Pat/)).toBeInTheDocument()

    const waiting = screen.getByRole('listitem', { name: 'Task #18' })
    expect(within(waiting).getByText('Awaiting approval')).toBeInTheDocument()
    expect(within(waiting).queryByText(/Approved by/)).not.toBeInTheDocument()
    expect(requested()).toEqual(['/api/tasks?status=active'])
  })

  it('switches filters and asks the backend for that status', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<TasksPage onShowOnMap={() => {}} />)
    await screen.findByRole('listitem', { name: 'Task #17' })
    expect(screen.getByRole('button', { name: 'Active', pressed: true })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Done' }))

    expect(await screen.findByRole('listitem', { name: 'Task #9' })).toBeInTheDocument()
    expect(screen.queryByRole('listitem', { name: 'Task #17' })).not.toBeInTheDocument()
    expect(requested()).toEqual(['/api/tasks?status=active', '/api/tasks?status=done'])
  })

  it('says so when there is nothing to show', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<TasksPage onShowOnMap={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rejected' }))

    expect(await screen.findByText('No rejected tasks.')).toBeInTheDocument()
  })

  it('shows a task on the map by its pick face', async () => {
    vi.stubGlobal('fetch', fetchMock)
    const onShowOnMap = vi.fn()
    render(<TasksPage onShowOnMap={onShowOnMap} />)

    const first = await screen.findByRole('listitem', { name: 'Task #17' })
    await userEvent.click(within(first).getByRole('button', { name: 'Show on map' }))

    expect(onShowOnMap).toHaveBeenCalledWith('C-01-01-1')
  })

  it('reloads on Refresh', async () => {
    vi.stubGlobal('fetch', fetchMock)
    render(<TasksPage onShowOnMap={() => {}} />)
    await screen.findByRole('listitem', { name: 'Task #17' })

    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }))

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('reports a load failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'boom' }), { status: 500 })),
    )
    render(<TasksPage onShowOnMap={() => {}} />)

    expect(await screen.findByText(/Couldn't load the tasks: boom/)).toBeInTheDocument()
  })
})
