// This side-effect import is required because jest-dom augments Vitest's expect at runtime.
// oxlint-disable-next-line import/no-unassigned-import
import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { FakeIntersectionObserver, resetIntersectionObservers } from './intersection-observer'
import { server } from './msw'

// TanStack Router restores scroll after navigation; jsdom intentionally omits this browser API.
window.scrollTo = () => undefined

// cmdk (the Command palette behind ItemSelect) observes its list size and
// scrolls the selected option into view; jsdom implements neither API.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
window.ResizeObserver = window.ResizeObserver ?? ResizeObserverStub

// jsdom ships no IntersectionObserver at all. Page tests click Load more;
// LoadMoreSentinel's own test fires the fake through intersect().
window.IntersectionObserver = window.IntersectionObserver ?? FakeIntersectionObserver
Element.prototype.scrollIntoView = () => undefined

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))

afterEach(() => {
  cleanup()
  resetIntersectionObservers()
  server.resetHandlers()
})

afterAll(() => server.close())
