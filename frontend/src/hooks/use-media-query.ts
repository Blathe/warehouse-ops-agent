import { useSyncExternalStore } from 'react'

// True while the browser window matches a CSS media query, e.g. '(min-width: 1024px)'.
// Updates when the window is resized across the breakpoint.
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}
