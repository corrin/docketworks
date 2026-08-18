/**
 * The progress stream for a payroll-posting run.
 *
 * Opus: The POST that starts a run answers with a `stream_url`; this opens it and
 * yields the run's events until it ends. The server does the posting in a
 * background task and this endpoint only replays what that task published, so
 * connecting late — or reconnecting — still delivers the whole run from the
 * beginning.
 *
 * Opus: It lives beside the generated client rather than inside the timesheet
 * feature because it speaks to the API directly, which ADR 0021 keeps in
 * src/api. It is not a generated function: an endless response is not an axios
 * response, and the endpoint is deliberately outside ninja for that reason.
 *
 * Opus: `EventSource` is not used despite being the obvious tool: it cannot report a
 * non-200 status, so an expired run (404) or a session that lapsed (401) would
 * surface as an indistinguishable connection error, and this screen has to
 * tell the operator which one happened. `fetch` exposes the status.
 */

const FRAME_SEPARATOR = '\n\n'
const DATA_PREFIX = 'data: '

/** One staff member's outcome, as the run reports it. */
export interface PayrollCompleteEvent {
  event: 'complete'
  staff_id: string
  staff_name: string
  success: boolean
  timesheet_id: string | null
  entries_posted: number
  work_hours: number
  other_leave_hours: number
  leave_hours: number
  skipped: boolean
  reason: string | null
  has_entries: boolean
  error: string | null
  posting_mode: 'timesheet' | 'salary'
  salary_timesheet_removed: boolean
}

export type PayrollPostEvent =
  | { event: 'start'; total: number }
  | { event: 'progress'; staff_id: string; staff_name: string; current: number; total: number }
  | PayrollCompleteEvent
  | { event: 'error'; message: string }
  | { event: 'done'; successful: number; failed: number }

function isPayrollPostEvent(value: unknown): value is PayrollPostEvent {
  return (
    typeof value === 'object' && value !== null && typeof Reflect.get(value, 'event') === 'string'
  )
}

/**
 * Open a posting run's stream and yield its events in order.
 *
 * Opus: Throws on a non-200 so the caller can show why the run cannot be watched
 * rather than a stalled progress bar. Frames that do not parse are skipped:
 * a single malformed frame must not discard the outcomes that follow it.
 */
export async function* streamPayrollPost(
  streamUrl: string,
  signal?: AbortSignal,
): AsyncGenerator<PayrollPostEvent> {
  const response = await fetch(streamUrl, {
    headers: { Accept: 'text/event-stream' },
    credentials: 'same-origin',
    signal,
  })
  if (!response.ok) {
    throw new Error(`Could not follow the payroll posting run (HTTP ${response.status}).`)
  }
  if (!response.body) {
    throw new Error('The payroll posting run returned no progress stream.')
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    for (;;) {
      // Opus: Reading a stream IS sequential: each chunk only exists once the
      // previous one is consumed, so there is no set of promises to run in
      // parallel. Same reason as data-versions-stream.ts.
      // oxlint-disable-next-line no-await-in-loop
      const { done, value } = await reader.read()
      if (done) return
      buffer += value
      // Opus: A chunk can split a frame, so only whole frames are consumed and the
      // remainder stays buffered for the next read.
      let separator = buffer.indexOf(FRAME_SEPARATOR)
      while (separator !== -1) {
        const frame = buffer.slice(0, separator)
        buffer = buffer.slice(separator + FRAME_SEPARATOR.length)
        const event = parseFrame(frame)
        if (event) yield event
        separator = buffer.indexOf(FRAME_SEPARATOR)
      }
    }
  } finally {
    await reader.cancel()
  }
}

function parseFrame(frame: string): PayrollPostEvent | null {
  const line = frame.split('\n').find((candidate) => candidate.startsWith(DATA_PREFIX))
  if (!line) return null
  try {
    const parsed: unknown = JSON.parse(line.slice(DATA_PREFIX.length))
    return isPayrollPostEvent(parsed) ? parsed : null
  } catch {
    // Opus: deliberate-swallow: one unreadable frame must not discard the run's
    // remaining outcomes, which are the part the operator acts on.
    return null
  }
}
