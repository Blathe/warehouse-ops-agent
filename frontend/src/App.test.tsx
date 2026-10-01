import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

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

const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
  if (url === '/api/models') return json(models)
  return json({
    conversation_id: 'conv_1',
    model: 'claude-haiku-4-5',
    status: 'done',
    reply: 'Cheap answer.',
    pending: [],
    tool_calls: [],
  })
})

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  localStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe('App model picker', () => {
  it('defaults to the backend default and lists prices', async () => {
    render(<App />)
    const picker = await screen.findByLabelText('Model')
    expect(picker).toHaveValue('claude-opus-5-5')
    expect(within(picker).getByText('Claude Haiku 4.5 ($1 / $5 per M tokens)')).toBeInTheDocument()
  })

  it('sends the chosen model, remembers it and labels the reply', async () => {
    render(<App />)
    await userEvent.selectOptions(await screen.findByLabelText('Model'), 'claude-haiku-4-5')
    await userEvent.type(screen.getByLabelText('Message'), 'hi{Enter}')

    expect(await screen.findByText('Cheap answer.')).toBeInTheDocument()
    expect(screen.getByText('Claude Haiku 4.5')).toBeInTheDocument()
    const chatCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat')
    expect(JSON.parse(chatCall?.[1]?.body as string).model).toBe('claude-haiku-4-5')
    expect(localStorage.getItem('warehouse-ops.model')).toBe('claude-haiku-4-5')
  })

  it('restores a remembered model', async () => {
    localStorage.setItem('warehouse-ops.model', 'claude-haiku-4-5')
    render(<App />)
    expect(await screen.findByLabelText('Model')).toHaveValue('claude-haiku-4-5')
  })
})
