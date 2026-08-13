/**
 * The data-version push channel: one long-lived SSE connection per tab.
 *
 * The server pushes the same document `GET /api/data-versions/` returns, so a
 * consumer needs no second parser and no second shape — the stream is a faster
 * delivery of the polling sibling's answer, not a new contract. Delivery is
 * the only difference, which is why this lives beside the generated client
 * rather than inside a feature (ADR 0021: generated-client imports stay in
 * src/api).
 *
 * Rejected alternative: declaring the stream as a ninja operation with
 * `openapi_extra` so hey-api would generate a typed SSE function instead of
 * this hand-written wrapper. The operation would still not be callable through
 * the generated axios client (an endless response is not an axios response),
 * the schema shape for a text/event-stream body is exactly the corner of
 * openapi-ts this repo has never exercised, and a codegen surprise this close
 * to cutover costs more than the ~40 lines it would remove. The wrapper still
 * uses the generated `createSseClient` for the wire work — frame parsing,
 * Last-Event-ID, backoff — so nothing here re-implements SSE (ADR 0032).
 *
 * Auth is the HttpOnly `access_token` cookie: same-origin, sent by the fetch
 * below, and checked by the view before the stream opens.
 */
import { createSseClient } from './generated/core/serverSentEvents.gen'
import type { DataVersions } from './generated/types.gen'

/**
 * Same path as the polling sibling, one segment deeper. Resolved against the
 * page origin before use: `createSseClient` builds a `Request`, and a relative
 * URL only resolves against the document in a browser — under jsdom the same
 * call throws `Invalid URL`, which the retry loop would turn into a silent
 * permanent outage rather than a test failure.
 */
const STREAM_PATH = '/api/data-versions/stream/'

/** The one event this channel carries data on. */
const DATA_VERSIONS_EVENT = 'data_versions'

/**
 * django-eventstream's own first frame, sent on every connection. Its payload
 * is proxy-defeating padding rather than JSON, so it is never read — only its
 * arrival matters, as proof the tab is connected and owes itself a catch-up.
 */
const STREAM_OPEN_EVENT = 'stream-open'

/**
 * How long to wait before re-opening a stream the server ended cleanly.
 * Matches the generated client's own base retry delay: a server that ends
 * every connection immediately (a proxy misconfiguration, a crash loop) would
 * otherwise be answered by an unthrottled reconnect loop.
 */
const REOPEN_DELAY_MS = 3_000

const DATA_VERSION_KEYS = [
  'crm_calls',
  'kanban',
  'kanban_related',
  'stock',
] as const satisfies readonly (keyof DataVersions)[]

export interface DataVersionsStreamHandlers {
  /** Aborting it closes the connection and stops the re-open loop for good. */
  signal: AbortSignal
  /** A pushed version document, already shape-checked. */
  onDataVersions: (versions: DataVersions) => void
  /** The tab is connected and has missed whatever happened while it was not. */
  onStreamOpen: () => void
  /**
   * The connection failed and the client is backing off before trying again —
   * a refused connection or a broken socket, the two states a tab cannot get
   * out of by itself. Deliberately NOT called for the two conditions that look
   * similar and are not: a stream the server ended cleanly (re-opened seconds
   * later, and the failed re-open reports itself here) and a malformed frame
   * (the connection is still open and still delivering). Both of those would
   * hand the caller a disconnection that never ends.
   *
   * The cause is deliberately not passed on — the caller's answer to either is
   * the same (fall back to polling and say so once), console logging is banned
   * by the E2E console guard, and a cause with nowhere to go is a parameter
   * that reads as if it were used.
   */
  onDisconnect: () => void
}

/**
 * Hold the stream open until `signal` aborts, reporting every event.
 *
 * `createSseClient` owns retrying a *failed* connection (3s doubling to 30s,
 * uncapped here on purpose: an outage that outlasts a fixed attempt count must
 * still recover without a page reload). It does not re-open a stream that
 * ended cleanly — it returns instead — which is what the outer loop is for.
 */
export async function runDataVersionsStream({
  signal,
  onDataVersions,
  onStreamOpen,
  onDisconnect,
}: DataVersionsStreamHandlers): Promise<void> {
  const url = new URL(STREAM_PATH, window.location.origin).toString()

  while (!signal.aborted) {
    const { stream } = createSseClient({
      url,
      signal,
      // Pinned rather than inherited: this request's only credential is the
      // HttpOnly cookie, and fetch's default is what sends it.
      credentials: 'same-origin',
      onSseError: () => {
        // An abort reaches the client as a fetch rejection like any other, and
        // reporting a disconnect the caller asked for would toast on unmount.
        if (signal.aborted) return
        onDisconnect()
      },
      onSseEvent: (event) => {
        if (event.event === STREAM_OPEN_EVENT) {
          onStreamOpen()
          return
        }
        // Anything else is the ~20s keep-alive frame, or a frame a future
        // server adds: unknown events are ignored, never guessed at.
        if (event.event !== DATA_VERSIONS_EVENT) return
        if (!isDataVersions(event.data)) {
          // Dropped, and nothing else. The connection is open and still
          // delivering, so the next well-formed push recovers on its own.
          //
          // Rejected alternative: reporting this as a disconnect. Nothing
          // disconnected, so no `stream-open` would ever follow to undo it,
          // and the caller would sit permanently in the one state it must
          // never be in — poll re-armed AND the push trigger still live.
          // Also rejected: aborting the connection to manufacture that
          // `stream-open`. A document this guard rejects is a server that
          // changed the shape of `current_data_versions()`, which fails the
          // polling sibling's consumers identically (that response is not
          // validated either) — so it is not evidence that this connection is
          // the broken part, and reconnecting would not fix it.
          return
        }
        onDataVersions(event.data)
      },
    })

    // Both awaits below are suppressed for the same reason, and it is the one
    // no-await-in-loop cannot see: this loop holds ONE connection at a time
    // for as long as the tab lives. There is no set of promises to gather and
    // run in parallel — running two of these at once would be two streams.

    // Draining is what pumps the connection: the generator only reads from the
    // response body while a consumer pulls. Every event has already been
    // delivered through onSseEvent, so the yielded payloads are dropped here.
    // oxlint-disable-next-line no-await-in-loop
    for await (const delivered of stream) {
      void delivered
    }

    if (signal.aborted) break
    // The generator returned without an abort, so the server ended the stream:
    // a deploy, a worker restart, a proxy lifetime cap. Deliberately not
    // reported. It is over in REOPEN_DELAY_MS, every tab meets it at once, and
    // the report on the other end of onDisconnect is a toast about a
    // persistent outage. The re-open below says what happened either way — it
    // reports through onSseError if it fails, and clears the caller's streak
    // through onStreamOpen if it succeeds.
    // oxlint-disable-next-line no-await-in-loop
    await delay(REOPEN_DELAY_MS, signal)
  }
}

/** A sleep that ends early on abort, so unmount never waits out a reconnect. */
function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = (): void => {
      clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = setTimeout(finish, ms)
    signal.addEventListener('abort', finish)
  })
}

/**
 * Every key present and a string, or the payload is not a version document.
 * The check is total rather than a spot-check of `kanban`: a consumer diffs
 * whichever key it tracks, and a document missing one of them would go
 * undetected until that consumer read `undefined` as a version.
 */
function isDataVersions(value: unknown): value is DataVersions {
  if (typeof value !== 'object' || value === null) return false
  const versionKeys = new Set(
    Object.entries(value)
      .filter(([, version]) => typeof version === 'string')
      .map(([key]) => key),
  )
  return DATA_VERSION_KEYS.every((key) => versionKeys.has(key))
}
