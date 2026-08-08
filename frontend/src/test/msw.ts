import { setupServer } from 'msw/node'

/** Keep handlers test-local so a test cannot silently rely on another feature's canned response. */
export const server = setupServer()
