// Runs before every test file: adds DOM matchers like toBeInTheDocument().
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import { toast } from 'sonner'

// Toasts live in a module-level store, so clear them or one test's toast shows up in the next.
afterEach(() => {
  cleanup()
  toast.dismiss()
})

// jsdom lacks the browser observers the message scroller uses.
class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}
for (const name of ['ResizeObserver', 'IntersectionObserver'] as const) {
  if (!(name in globalThis)) {
    Object.defineProperty(globalThis, name, { value: NoopObserver, writable: true })
  }
}
Element.prototype.scrollTo ??= function () {}
Element.prototype.scrollIntoView ??= function () {} // the command palette scrolls to the active item
// jsdom lacks pointer capture, which toasts use for swipe-to-dismiss.
Element.prototype.setPointerCapture ??= function () {}
Element.prototype.releasePointerCapture ??= function () {}

// jsdom has no matchMedia; the sidebar uses it to tell phones from desktops. Tests ask for
// reduced motion so numbers and transitions land instantly instead of animating.
window.matchMedia ??= (query: string) =>
  ({
    matches: query.includes('prefers-reduced-motion'),
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  }) as MediaQueryList
