import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Bay, FloorMapData } from '@/lib/api'
import { FloorMap } from './FloorMap'

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

function mockFetch(response: Response) {
  vi.stubGlobal('fetch', vi.fn(async () => response))
}

afterEach(() => vi.unstubAllGlobals())

describe('FloorMap', () => {
  it('shows each bay with its status and the legend counts', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<FloorMap />)

    expect(await screen.findByText('Zone A: small tackle')).toBeInTheDocument()
    expect(screen.getByText('Zone B: rods & reels')).toBeInTheDocument()
    expect(screen.getByText('Empty (1)')).toBeInTheDocument()
    expect(
      screen.getByRole('button', {
        name: 'A-03-04-1, Empty, SKU 58368, 0 on hand, open task #18',
      }),
    ).toBeInTheDocument()
  })

  it('shows a bay’s stock when clicked', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<FloorMap />)

    await userEvent.click(await screen.findByRole('button', { name: /^A-03-04-1/ }))

    expect(screen.getByText('Hollow Pine Circle Hook 2/0 25pk')).toBeInTheDocument()
    expect(screen.getByText('0 (min 36, max 144)')).toBeInTheDocument()
    expect(screen.getByText('Replenishment task #18 open')).toBeInTheDocument()
    expect(screen.getByText('552 × SKU 58368 (LPN98259272)')).toBeInTheDocument()
  })

  it('explains an empty, unassigned pick face', async () => {
    mockFetch(new Response(JSON.stringify(data)))
    render(<FloorMap />)
    await userEvent.click(await screen.findByRole('button', { name: /^B-01-01-1/ }))
    expect(screen.getByText('No SKU slotted in this pick face')).toBeInTheDocument()
  })

  it('shows an error when the backend is down', async () => {
    mockFetch(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }))
    render(<FloorMap />)
    expect(await screen.findByText("Couldn't load the floor map: boom")).toBeInTheDocument()
  })
})
