/**
 * The payroll run channel: one long-lived SSE connection while the panel is open.
 *
 * Opus: The server pushes exactly the document `GET /api/timesheets/payroll/runs/`
 * returns, so a consumer needs no second parser and no second shape — the stream
 * is a faster delivery of the polling sibling's answer, not a new contract. That
 * is why this lives beside the generated client rather than inside the timesheet
 * feature (ADR 0021: generated-client imports stay in src/api).
 *
 * Opus: This replaces a hand-rolled `fetch` + `TextDecoderStream` frame parser and
 * a hand-declared 14-field mirror of the server's event shapes — a second SSE
 * implementation beside the generated `createSseClient` that data-versions
 * already used (ADR 0032, ADR 0039). The reason given for hand-rolling it was
 * that `EventSource` cannot report a non-200, so an expired run (404) and a
 * lapsed session (401) would be indistinguishable. That reason is answered
 * without a second parser: the polling sibling is generated axios with typed
 * errors, so IT tells those apart, and the stream is only the accelerator.
 *
 * Auth is the HttpOnly `access_token` cookie: same-origin, sent by the fetch
 * below, and checked by the view before the stream opens. Superuser-only — the
 * document carries names, hours and pay basis, which is also why it has its own
 * channel rather than an event on the data-versions one.
 */
import { createSseClient } from './generated/core/serverSentEvents.gen'
import { zPayrollRunsOut } from './generated/zod.gen'

import type { PayrollRunsOut } from './generated/types.gen'

/** Same path as the polling sibling, one segment deeper. */
const STREAM_PATH = '/api/timesheets/payroll/runs/stream/'

/** The one event this channel carries data on. */
const PAYROLL_RUNS_EVENT = 'payroll_runs'

/**
 * django-eventstream's own first frame, sent on every connection. Its payload is
 * proxy-defeating padding rather than JSON, so it is never read — only its
 * arrival matters, as proof the tab is connected and owes itself a catch-up.
 */
const STREAM_OPEN_EVENT = 'stream-open'

/** How long to wait before re-opening a stream the server ended cleanly. */
const REOPEN_DELAY_MS = 3_000

const RUN_KEYS = ['post'] as const satisfies readonly (keyof PayrollRunsOut)[]

/**
 * A slot the generated `PayrollRunsOut` gained that this consumer does not
 * handle: `AssertNever` only accepts `never`, so adding a run kind on the server
 * is a TypeScript error here rather than a slot silently ignored. The same trick
 * guards the data-versions document.
 */
type MissingRunKeys = Exclude<keyof PayrollRunsOut, (typeof RUN_KEYS)[number]>
type AssertNever<T extends never> = T
export type RunKeysExhaustive = AssertNever<MissingRunKeys>

export interface PayrollRunsStreamHandlers {
  /** Aborting it closes the connection and stops the re-open loop for good. */
  signal: AbortSignal
  /** A pushed run document, already shape-checked. */
  onRuns: (runs: PayrollRunsOut) => void
  /** The tab is connected and owes itself whatever it missed while it was not. */
  onStreamOpen: () => void
}

/** Hold the stream open until `signal` aborts, reporting every document. */
export async function runPayrollRunsStream({
  signal,
  onRuns,
  onStreamOpen,
}: PayrollRunsStreamHandlers): Promise<void> {
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
        // Anything else is the keep-alive, or a frame a future server adds:
        // unknown events are ignored, never guessed at.
        if (event.event !== PAYROLL_RUNS_EVENT) return
        if (!isPayrollRuns(event.data)) {
          // Dropped, and nothing else. One unreadable frame must not discard the
          // outcomes that follow it — those per-staff results are the part the
          // operator acts on. The connection is open and still delivering, so
          // the next well-formed push recovers on its own.
          return
        }
        onRuns(event.data)
      },
    })

    // Draining is what pumps the connection: the generator only reads from the
    // response body while a consumer pulls, and every document has already been
    // delivered through onSseEvent. One connection at a time by construction, so
    // there is no set of promises to run in parallel.
    // oxlint-disable-next-line no-await-in-loop
    for await (const delivered of stream) {
      void delivered
    }

    if (signal.aborted) break
    // The generator returned without an abort, so the server ended the stream: a
    // deploy, a worker restart, a proxy lifetime cap. Deliberately not reported —
    // the poll still answers, and the re-open below says what happened either way.
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
 * The generated schema, in full — not a key spot-check. The handler's contract
 * says "already shape-checked", and a check that only proved the keys existed
 * let `{post: "garbage"}` through to every consumer that read `post.status`.
 * One validator per shape (ADR 0039): the same zod schema the generated client
 * uses for the polling sibling.
 */
function isPayrollRuns(value: unknown): value is PayrollRunsOut {
  return zPayrollRunsOut.safeParse(value).success
}
