import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

/**
 * The one shared handler, because the kanban board opens the data-version SSE
 * stream on mount and `onUnhandledRequest: 'error'` would otherwise fail every
 * test that renders it. It answers with a connection that never emits and never
 * ends — connected but quiet, which is the "nothing to push" case and leaves
 * the fallback poll armed, so tests written against the poll behave as before.
 *
 * It is passed to setupServer rather than added per test because
 * `server.resetHandlers()` between tests restores exactly this list. A test
 * driving the stream overrides it with `server.use()`.
 */
const quietDataVersionsStream = http.get(
  '*/api/data-versions/stream/',
  () =>
    new HttpResponse(new ReadableStream(), {
      headers: { 'Content-Type': 'text/event-stream' },
    }),
)

/** Keep handlers test-local so a test cannot silently rely on another feature's canned response. */
export const server = setupServer(quietDataVersionsStream)
