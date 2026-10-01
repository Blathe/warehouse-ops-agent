// Runs before every test file: adds DOM matchers like toBeInTheDocument().
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

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
