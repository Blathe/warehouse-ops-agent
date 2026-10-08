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
