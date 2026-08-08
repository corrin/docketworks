// This side-effect import is required because jest-dom augments Vitest's expect at runtime.
// oxlint-disable-next-line import/no-unassigned-import
import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { server } from './msw'

// TanStack Router restores scroll after navigation; jsdom intentionally omits this browser API.
window.scrollTo = () => undefined

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))

afterEach(() => {
  cleanup()
  server.resetHandlers()
})

afterAll(() => server.close())
