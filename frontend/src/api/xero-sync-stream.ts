/**
 * The Xero sync-progress channel: one long-lived SSE connection while the
 * connection page is open.
 *
 * Fable: Lives beside the generated client like its two siblings (ADR 0021:
 * generated-client imports stay in src/api), reusing the generated
 * `createSseClient` rather than a second SSE implementation (ADR 0039). The
 * stream is the accelerator; the polling sibling `GET /api/xero/sync-info/`
 * answers "is a run in flight" for a tab that connects late.
 *
 * Fable: Unlike the payroll stream there is no generated zod schema to
 * validate against — the worker's progress events are outside the OpenAPI
 * schema by design (a never-ending response the axios client cannot call) —
 * so the shape below is the one hand-declared mirror, kept to exactly the
 * fields the page reads and guarded at runtime.
 *
 * Auth is the HttpOnly `access_token` cookie; the view is office-gated, which
 * is also why sync progress has its own channel rather than an event on the
 * any-staff data-versions one (events carry AppError ids).
 */
import { createSseClient } from './generated/core/serverSentEvents.gen'

/** Same path as the polling sibling, one segment deeper. */
const STREAM_PATH = '/api/xero/sync/stream/'

/** The one event type the worker publishes. */
const SYNC_EVENT = 'message'

/** django-eventstream's own first frame; arrival = connected, payload unread. */
const STREAM_OPEN_EVENT = 'stream-open'

/** How long to wait before re-opening a stream the server ended cleanly. */
const REOPEN_DELAY_MS = 3_000

/** The fields the page reads from a worker progress event. */
export interface XeroSyncEvent {
  datetime: string
  entity: string
  severity: 'info' | 'warning' | 'error'
  message: string
  /** Present only on the terminal "Sync stream ended" event. */
  sync_status?: 'success' | 'aborted' | 'error'
  overall_progress?: number
  entity_progress?: number
  error_id?: string
  task_id?: string
}

const SEVERITIES = new Set(['info', 'warning', 'error'])

function isSyncEvent(value: unknown): value is XeroSyncEvent {
  if (typeof value !== 'object' || value === null) return false
  if (!('datetime' in value && 'entity' in value && 'message' in value && 'severity' in value)) {
    return false
  }
  return (
    typeof value.datetime === 'string' &&
    typeof value.entity === 'string' &&
    typeof value.message === 'string' &&
    typeof value.severity === 'string' &&
    SEVERITIES.has(value.severity)
  )
}

export interface XeroSyncStreamHandlers {
  /** Aborting it closes the connection and stops the re-open loop for good. */
  signal: AbortSignal
  /** A pushed progress event, already shape-checked. */
  onEvent: (event: XeroSyncEvent) => void
  /** The tab is connected; a late joiner owes itself one sync-info fetch. */
  onStreamOpen: () => void
}

/** Hold the stream open until `signal` aborts, reporting every event. */
export async function runXeroSyncStream({
  signal,
  onEvent,
  onStreamOpen,
}: XeroSyncStreamHandlers): Promise<void> {
  const url = new URL(STREAM_PATH, window.location.origin).toString()

  while (!signal.aborted) {
    const { stream } = createSseClient({
      url,
      signal,
      // Pinned rather than inherited: this request's only credential is the
      // HttpOnly cookie, and fetch's default is what sends it.
      credentials: 'same-origin',
      onSseEvent: (event) => {
        if (event.event === STREAM_OPEN_EVENT) {
          onStreamOpen()
          return
        }
        if (event.event !== SYNC_EVENT) return
        if (!isSyncEvent(event.data)) {
          // Dropped, and nothing else: one unreadable frame must not discard
          // the run's remaining events; the connection is still delivering.
          return
        }
        onEvent(event.data)
      },
    })

    // Draining is what pumps the connection: events were already delivered
    // through onSseEvent. One connection at a time by construction.
    // oxlint-disable-next-line no-await-in-loop
    for await (const delivered of stream) {
      void delivered
    }

    if (signal.aborted) break
    // Server ended the stream (deploy, worker restart, proxy lifetime cap):
    // reconnect quietly; the polling sibling covers the gap.
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
