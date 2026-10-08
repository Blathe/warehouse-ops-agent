import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useCountUp } from './use-count-up'

function motion(reduced: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduced && query.includes('prefers-reduced-motion'),
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }))
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useCountUp', () => {
  it('shows the number straight away when motion is reduced', () => {
    motion(true)
    const { result, rerender } = renderHook(({ n }) => useCountUp(n), { initialProps: { n: 12 } })
    expect(result.current).toBe(12)

    rerender({ n: 30 })

    expect(result.current).toBe(30)
  })

  it('counts up from zero, then from the old number to a new one', () => {
    motion(false)
    vi.useFakeTimers()
    const { result, rerender } = renderHook(({ n }) => useCountUp(n, 1000), {
      initialProps: { n: 100 },
    })
    expect(result.current).toBe(0)

    act(() => void vi.advanceTimersByTime(400))
    expect(result.current).toBeGreaterThan(0)
    expect(result.current).toBeLessThan(100)

    act(() => void vi.advanceTimersByTime(1000))
    expect(result.current).toBe(100)

    rerender({ n: 40 })
    act(() => void vi.advanceTimersByTime(1100))
    expect(result.current).toBe(40)
  })
})
