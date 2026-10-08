import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Bay, FloorMapData } from '@/lib/api'
import { FloorMapPage } from './FloorMapPage'

function bay(location: string, overrides: Partial<Bay['pick']> = {}): Bay {
  const [zone, aisle, number] = location.split('-')
  return {
    zone,
    aisle: Number(aisle),
    bay: Number(number),
    x: 0,
    y: 0,
    pick: {
      location,
      sku_code: '58368',
      description: 'Hollow Pine Circle Hook 2/0 25pk',
      on_hand: 100,
      min_qty: 36,
      max_qty: 144,
      status: 'ok',
      open_task_id: null,
      ...overrides,
    },
    reserve: [
      { location: location.replace(/-1$/, '-2'), level: 2, sku_code: '58368', lpn: 'LPN98259272', qty: 552 },
      { location: location.replace(/-1$/, '-3'), level: 3, sku_code: null, lpn: null, qty: 0 },
    ],
    open_discrepancies: [],
  }
}

const data: FloorMapData = {
  bays: [
    bay('A-03-04-1', { on_hand: 0, status: 'empty', open_task_id: 18 }),
    bay('A-03-05-1'),
    bay('B-01-01-1', { sku_code: null, description: null, min_qty: null, max_qty: null, on_hand: 0, status: 'unassigned' }),
  ],
  staging: [],
  counts: { ok: 1, low: 0, empty: 1, unassigned: 1 },
}

// The app keeps the selected bay in its own state; this stands in for that.
function Page({ highlight = [] }: { highlight?: string[] }) {
  const [selected, setSelected] = useState<string | null>(null)
  return <FloorMapPage selected={selected} onSelect={setSelected} highlight={highlight} />
}

function mockFetch(response: Response) {
  vi.stubGlobal('fetch', vi.fn(async () => response))
}

afterEach(() => vi.unstubAllGlobals())

describe('FloorMapPage', () => {
  it('shows each bay with its status and the legend counts', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<Page />)

    expect(await screen.findByRole('region', { name: 'Zone A: small tackle' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Zone B: rods & reels' })).toBeInTheDocument()
    expect(screen.getByText('Empty (1)')).toBeInTheDocument()
    expect(
      screen.getByRole('button', {
        name: 'A-03-04-1, Empty, SKU 58368, 0 on hand, open task #18',
      }),
    ).toBeInTheDocument()
  })

  it('shows a bay’s stock when clicked', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<Page />)

    await userEvent.click(await screen.findByRole('button', { name: /^A-03-04-1/ }))

    expect(screen.getByText('Hollow Pine Circle Hook 2/0 25pk')).toBeInTheDocument()
    expect(screen.getByText('0 (min 36, max 144)')).toBeInTheDocument()
    expect(screen.getByText('Replenishment task #18 open')).toBeInTheDocument()
    expect(screen.getByText('552 × SKU 58368 (LPN98259272)')).toBeInTheDocument()
  })

  it('explains an empty, unassigned pick face', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<Page />)
    await userEvent.click(await screen.findByRole('button', { name: /^B-01-01-1/ }))
    expect(screen.getByText('No SKU slotted in this pick face')).toBeInTheDocument()
  })

  it('shows an error when the backend is down', async () => {
    mockFetch(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }))
    render(<Page />)
    expect(await screen.findByText("Couldn't load the floor map: boom")).toBeInTheDocument()
  })

  it('filters the map to one zone and recounts the legend', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<Page />)
    await screen.findByRole('region', { name: 'Zone B: rods & reels' })

    await userEvent.click(screen.getByRole('button', { name: 'Zone A' }))

    expect(screen.queryByRole('region', { name: 'Zone B: rods & reels' })).not.toBeInTheDocument()
    const legend = screen.getByRole('list', { name: 'Legend' })
    expect(within(legend).getByText('No SKU slotted (0)')).toBeInTheDocument()
    expect(within(legend).getByText('OK (1)')).toBeInTheDocument()
  })

  it('switches between status colours and stock level shading', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<Page />)
    const cell = await screen.findByRole('button', { name: /^A-03-05-1/ })
    expect(cell).not.toHaveAttribute('style')

    await userEvent.click(screen.getByRole('button', { name: 'Stock level' }))

    // 100 of max 144 on hand, so the cell is shaded about 69% full.
    expect(screen.getByRole('button', { name: /^A-03-05-1/ }).getAttribute('style')).toContain('69%')
    expect(screen.getByText('Full')).toBeInTheDocument()
  })

  it('pulses the bays the agent is working on', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<Page highlight={['A-03-05-1']} />)

    expect(await screen.findByRole('button', { name: /^A-03-05-1/ })).toHaveClass('animate-pulse')
    expect(screen.getByRole('button', { name: /^A-03-04-1/ })).not.toHaveClass('animate-pulse')
  })
})
