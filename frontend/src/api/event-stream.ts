/**
 * The one SSE-consumer scaffold behind every eventstream channel.
 *
 * Fable: hoisted when the Xero sync stream became the third copy of the
 * open/deliver/drain/reopen loop and its abort-aware delay (ADR 0039). Each
 * channel keeps its own file for its path, event name, payload guard and the
 * rationale comments that are genuinely per-channel; the mechanics live here.
 *
 * `createSseClient` owns retrying a *failed* connection (3s doubling to 30s,
 * uncapped on purpose: an outage that outlasts a fixed attempt count must
 * still recover without a page reload). It does not re-open a stream that
 * ended cleanly — it returns instead — which is what the outer loop is for.
 */
import { createSseClient } from './generated/core/serverSentEvents.gen'

/**
 * django-eventstream's own first frame, sent on every connection. Its payload
 * is proxy-defeating padding rather than JSON, so it is never read — only its
 * arrival matters, as proof the tab is connected and owes itself a catch-up
 * from the channel's polling sibling.
 */
const STREAM_OPEN_EVENT = 'stream-open'

/** How long to wait before re-opening a stream the server ended cleanly. */
const REOPEN_DELAY_MS = 3_000

export interface EventStreamOptions<TEvent> {
  /** The channel's URL path, one segment deeper than its polling sibling. */
  path: string
  /** The one event name this channel carries data on. */
  eventName: string
  /** The channel's payload guard; a frame it rejects is dropped, and nothing
   * else — one unreadable frame must not discard the events that follow it,
   * and the connection is still delivering. */
  isEvent: (value: unknown) => value is TEvent
  /** Aborting it closes the connection and stops the re-open loop for good. */
  signal: AbortSignal
  /** A pushed event, already shape-checked. */
  onEvent: (event: TEvent) => void
  /** The tab is connected and owes itself whatever it missed while it was not. */
  onStreamOpen: () => void
  /** Optional: the connection dropped uncleanly (never fired for an abort the
   * caller asked for). Channels without a disconnect UI omit it. */
  onDisconnect?: () => void
}

/** Hold the stream open until `signal` aborts, reporting every event. */
export async function runEventStream<TEvent>({
  path,
  eventName,
  isEvent,
  signal,
  onEvent,
  onStreamOpen,
  onDisconnect,
}: EventStreamOptions<TEvent>): Promise<void> {
  const url = new URL(path, window.location.origin).toString()

  while (!signal.aborted) {
    const { stream } = createSseClient({
      url,
      signal,
      // Pinned rather than inherited: this request's only credential is the
      // HttpOnly cookie, and fetch's default is what sends it.
      credentials: 'same-origin',
      onSseError: () => {
        // An abort reaches the client as a fetch rejection like any other,
        // and reporting a disconnect the caller asked for would toast on
        // unmount.
        if (signal.aborted) return
        onDisconnect?.()
      },
      onSseEvent: (event) => {
        if (event.event === STREAM_OPEN_EVENT) {
          onStreamOpen()
          return
        }
        // Anything else is the ~20s keep-alive frame, or a frame a future
        // server adds: unknown events are ignored, never guessed at.
        if (event.event !== eventName) return
        if (!isEvent(event.data)) return
        onEvent(event.data)
      },
    })

    // Draining is what pumps the connection: the generator only reads from
    // the response body while a consumer pulls, and every event has already
    // been delivered through onSseEvent. One connection at a time by
    // construction, so there is no set of promises to run in parallel.
    // oxlint-disable-next-line no-await-in-loop
    for await (const delivered of stream) {
      void delivered
    }

    if (signal.aborted) break
    // The generator returned without an abort, so the server ended the
    // stream: a deploy, a worker restart, a proxy lifetime cap. Deliberately
    // not reported — it is over in REOPEN_DELAY_MS and every tab meets it at
    // once; the re-open below reports through onSseError if it fails and
    // clears the caller's streak through onStreamOpen if it succeeds.
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
