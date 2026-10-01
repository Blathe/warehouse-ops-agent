import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

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

describe('ApprovalCard', () => {
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
