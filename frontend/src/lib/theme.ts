import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

export const THEME_KEY = 'warehouse-ops.theme'

// Browser storage can be unavailable (private mode), so never let it throw.
export function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(THEME_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

// What was saved, otherwise what the operating system prefers.
export function initialTheme(): Theme {
  return storedTheme() ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
}

// Tailwind's dark mode is the `dark` class on <html> (see @custom-variant in index.css).
export function applyTheme(theme: Theme, remember = true): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  if (!remember) return
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Not remembered between visits, which is fine.
  }
}

// The theme currently on the page, kept up to date when the toggle flips the `dark` class.
// (useSyncExternalStore is React's way to read state that lives outside React, here the
// <html> element's class list.)
export function useCurrentTheme(): Theme {
  return useSyncExternalStore(
    (onChange) => {
      const observer = new MutationObserver(onChange)
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
      return () => observer.disconnect()
    },
    () => (document.documentElement.classList.contains('dark') ? 'dark' : 'light'),
    () => 'light',
  )
}
