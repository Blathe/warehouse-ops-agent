import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApprovalCard } from './ApprovalCard'

const action = {
  tool_use_id: 'tu_1',
  tool: 'create_replenishment_task',
  input: {
    sku_code: '58368',
    from_location: 'A-03-06-2',
    to_location: 'A-03-04-1',
    qty: 144,
    reason: 'Pick face empty',
  },
}

const slot = (location: string, qty: number) => ({
  location,
  level: 2,
  sku_code: '58368',
  lpn: 'LPN1',
  qty,
})

const floorMap = {
  bays: [
    {
      zone: 'A',
      aisle: 3,
      bay: 4,
      x: 0,
      y: 0,
      pick: {
        location: 'A-03-04-1',
        sku_code: '58368',
        description: 'Hook',
        on_hand: 0,
        min_qty: 36,
        max_qty: 144,
        status: 'empty',
        open_task_id: null,
      },
      reserve: [slot('A-03-04-2', 10)],
      open_discrepancies: [],
    },
    {
      zone: 'A',
      aisle: 3,
      bay: 6,
      x: 0,
      y: 0,
      pick: { location: 'A-03-06-1', sku_code: null, description: null, on_hand: 0, min_qty: null, max_qty: null, status: 'unassigned', open_task_id: null },
      reserve: [slot('A-03-06-2', 552)],
      open_discrepancies: [],
    },
  ],
  staging: [],
  counts: { ok: 0, low: 0, empty: 1, unassigned: 1 },
}

afterEach(() => vi.unstubAllGlobals())

describe('ApprovalCard', () => {
  it('shows what the move does to the pick face and the reserve pallet', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(floorMap))))
    render(<ApprovalCard actions={[action]} busy={false} onDecide={() => {}} />)

    expect(await screen.findByRole('img', { name: 'Pick face A-03-04-1: 0 before, 144 after' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Reserve A-03-06-2: 552 before, 408 after' })).toBeInTheDocument()
    expect(screen.getByText('0 → 144')).toBeInTheDocument()
    expect(screen.getByText('552 → 408')).toBeInTheDocument()
  })

  it('still shows the move when the stock levels cannot be loaded', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    render(<ApprovalCard actions={[action]} busy={false} onDecide={() => {}} />)

    expect(screen.getByText('144 from A-03-06-2 to A-03-04-1')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('shows the proposed move', () => {
    render(<ApprovalCard actions={[action]} busy={false} onDecide={() => {}} />)
    expect(screen.getByText('58368')).toBeInTheDocument()
    expect(screen.getByText('144 from A-03-06-2 to A-03-04-1')).toBeInTheDocument()
    expect(screen.getByText('Pick face empty')).toBeInTheDocument()
  })

  it('reports the decision', async () => {
    const onDecide = vi.fn()
    render(<ApprovalCard actions={[action]} busy={false} onDecide={onDecide} />)
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(onDecide.mock.calls).toEqual([[false], [true]])
  })

  it('disables the buttons while busy', () => {
    render(<ApprovalCard actions={[action]} busy onDecide={() => {}} />)
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })
})
