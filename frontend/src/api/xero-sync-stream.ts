/**
 * The Xero sync-progress channel: one long-lived SSE connection while the
 * connection page is open.
 *
 * Fable: Lives beside the generated client like its two siblings (ADR 0021:
 * generated-client imports stay in src/api); the open/drain/reopen loop lives
 * once in `./event-stream` (ADR 0039). The stream is the accelerator; the
 * polling sibling `GET /api/xero/sync-info/` answers "is a run in flight" for
 * a tab that connects late.
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
import { runEventStream } from './event-stream'

/** Same path as the polling sibling, one segment deeper. */
const STREAM_PATH = '/api/xero/sync/stream/'

/** The one event type the worker publishes. */
const SYNC_EVENT = 'message'

/** The fields the page reads from a worker progress event. */
export interface XeroSyncEvent {
  datetime: string
  entity: string
  severity: 'info' | 'warning' | 'error'
  message: string
  /** Present only on terminal events (run finished, aborted, or failed). */
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
export function runXeroSyncStream({
  signal,
  onEvent,
  onStreamOpen,
}: XeroSyncStreamHandlers): Promise<void> {
  return runEventStream({
    path: STREAM_PATH,
    eventName: SYNC_EVENT,
    isEvent: isSyncEvent,
    signal,
    onEvent,
    onStreamOpen,
  })
}
