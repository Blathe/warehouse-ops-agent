import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WorkspaceLayout } from './WorkspaceLayout'

// Pretends the window is (or isn't) wide enough for the side-by-side layout.
function windowIs(wide: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: wide && query.includes('min-width'),
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('WorkspaceLayout', () => {
  it('puts chat and activity side by side with a draggable divider on a wide screen', () => {
    windowIs(true)
    render(<WorkspaceLayout view="chat" chat={<p>the chat</p>} activity={<p>the activity</p>} />)

    expect(screen.getByRole('region', { name: 'Chat' })).toHaveTextContent('the chat')
    expect(screen.getByText('the activity')).toBeInTheDocument()
    expect(screen.getByRole('separator', { name: 'Resize chat and activity' })).toBeInTheDocument()
  })

  it('shows one at a time on a narrow screen, without a divider', () => {
    windowIs(false)
    render(<WorkspaceLayout view="activity" chat={<p>the chat</p>} activity={<p>the activity</p>} />)

    expect(screen.queryByRole('separator')).not.toBeInTheDocument()
    expect(screen.getByText('the activity').parentElement).not.toHaveClass('hidden')
    expect(screen.getByRole('region', { name: 'Chat', hidden: true })).toHaveClass('hidden')
  })
})
