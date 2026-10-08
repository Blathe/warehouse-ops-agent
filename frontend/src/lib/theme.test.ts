import { afterEach, describe, expect, it } from 'vitest'

import { applyTheme, initialTheme, THEME_KEY } from '@/lib/theme'

afterEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

describe('theme', () => {
  it('applies the dark class and remembers the choice', () => {
    applyTheme('dark')
    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    expect(initialTheme()).toBe('dark')
  })

  it('removes the dark class for light', () => {
    applyTheme('dark')
    applyTheme('light')
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('falls back to the system preference when nothing is saved', () => {
    expect(initialTheme()).toBe('light') // the test setup's matchMedia never matches
  })
})
