import { setupServer } from 'msw/node'

/** Shared network boundary for DOM tests; individual tests own their handlers. */
export const server = setupServer()
