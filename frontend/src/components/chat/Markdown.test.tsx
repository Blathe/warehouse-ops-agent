import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Markdown } from './Markdown'

describe('Markdown', () => {
  it('renders a table as a table', () => {
    render(
      <Markdown>
        {[
          '| Location | SKU | Qty |',
          '|---|---|---|',
          '| A-03-04-1 | 58368 | 144 |',
          '| B-02-27-1 | 99974 | 4 |',
        ].join('\n')}
      </Markdown>,
    )

    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Location',
      'SKU',
      'Qty',
    ])
    expect(within(table).getAllByRole('row')).toHaveLength(3) // header plus two rows
    expect(within(table).getByRole('cell', { name: 'A-03-04-1' })).toBeInTheDocument()
    expect(screen.queryByText(/\|---\|/)).not.toBeInTheDocument()
  })

  it('renders bold text, lists and inline code', () => {
    render(
      <Markdown>{'**Empty faces**\n\n- A-03-04-1\n- A-01-19-1\n\n1. First\n2. Second\n\nUse `A-03-06-2`.'}</Markdown>,
    )

    expect(screen.getByText('Empty faces').tagName).toBe('STRONG')
    expect(screen.getAllByRole('list')).toHaveLength(2)
    expect(screen.getAllByRole('listitem')).toHaveLength(4)
    expect(screen.getByText('A-03-06-2').tagName).toBe('CODE')
  })

  it('opens links in a new tab without leaking the opener', () => {
    render(<Markdown>{'[docs](https://example.com/help)'}</Markdown>)

    const link = screen.getByRole('link', { name: 'docs' })
    expect(link).toHaveAttribute('href', 'https://example.com/help')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer noopener')
  })

  it('does not render raw HTML from the reply', () => {
    const { container } = render(
      <Markdown>{'Hello <img src=x onerror="alert(1)"> <script>alert(1)</script> <b>bold</b>'}</Markdown>,
    )

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
  })

  it('drops unsafe link targets', () => {
    const { container } = render(<Markdown>{'[click](javascript:alert(1))'}</Markdown>)

    const link = container.querySelector('a')
    expect(link?.getAttribute('href') ?? '').not.toMatch(/javascript/i)
  })

  it('keeps plain text as plain text', () => {
    render(<Markdown>{'Zone A has 4 short picks.'}</Markdown>)
    expect(screen.getByText('Zone A has 4 short picks.')).toBeInTheDocument()
  })
})
