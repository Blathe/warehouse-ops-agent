import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { OverviewData } from '@/lib/api'
import { OverviewPage } from './OverviewPage'

const hours = Array.from({ length: 24 }, (_, i) => ({
  hour_start: `2026-05-31T${String((14 + i) % 24).padStart(2, '0')}:00:00`,
  short_picks: i === 23 ? 4 : 0,
}))

const overview: OverviewData = {
  as_of: '2026-06-01T13:00:00',
  empty_faces: 7,
  low_faces: 12,
  short_picks_24h: 4,
  tasks_awaiting_approval: 1,
  tasks_approved: 2,
  open_discrepancies: 3,
  zones: [
    { zone: 'A', ok: 80, low: 6, empty: 4, unassigned: 10, short_picks: 3 },
    { zone: 'B', ok: 60, low: 6, empty: 3, unassigned: 10, short_picks: 1 },
  ],
  short_picks_by_hour: hours,
  urgent_needs: [
    {
      location: 'A-03-08-1',
      zone: 'A',
      sku_code: '94659',
      description: 'Bluegill Bay Offset Worm Hook #2 25pk',
      on_hand: 0,
      min_qty: 50,
      max_qty: 300,
      open_demand: 0,
      reasons: ['empty'],
      suggested_qty: 250,
    },
  ],
}

function renderPage(onShowOnMap = vi.fn()) {
  render(
    <MemoryRouter>
      <OverviewPage onShowOnMap={onShowOnMap} />
    </MemoryRouter>,
  )
  return onShowOnMap
}

afterEach(() => vi.unstubAllGlobals())

describe('OverviewPage', () => {
  it('shows the key numbers, charts and urgent pick faces', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(overview))))
    renderPage()

    const numbers = await screen.findByRole('region', { name: 'Key numbers' })
    expect(within(numbers).getByRole('link', { name: /Empty pick faces/ })).toHaveTextContent('7')
    expect(within(numbers).getByRole('link', { name: /Awaiting approval/ })).toHaveAttribute(
      'href',
      '/tasks',
    )
    expect(screen.getByRole('img', { name: 'Zone A: 4 empty, 6 low, 80 ok' })).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: '4 short picks in the last 24 hours, by hour' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Bluegill Bay Offset Worm Hook/)).toBeInTheDocument()
  })

  it('shows an urgent pick face on the map', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(overview))))
    const onShowOnMap = renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Show A-03-08-1 on the map' }))

    expect(onShowOnMap).toHaveBeenCalledWith('A-03-08-1')
  })

  it('says so when nothing is urgent', async () => {
    const calm = { ...overview, urgent_needs: [] }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(calm))))
    renderPage()

    expect(await screen.findByText(/Nothing urgent/)).toBeInTheDocument()
  })

  it('shows an error when the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    renderPage()

    expect(await screen.findByText(/Couldn't load the overview/)).toBeInTheDocument()
  })
})
