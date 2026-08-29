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
 * Last-Event-ID, backoff — so nothing here re-implements SSE (ADR 0032), and
 * the open/drain/reopen loop lives once in `./event-stream` (ADR 0039).
 *
 * Auth is the HttpOnly `access_token` cookie: same-origin, sent by the fetch,
 * and checked by the view before the stream opens.
 */
import { runEventStream } from './event-stream'

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

const DATA_VERSION_KEYS = [
  'crm_calls',
  'kanban',
  'kanban_related',
  'stock',
] as const satisfies readonly (keyof DataVersions)[]

/**
 * A key the generated DataVersions type gained but this list did not: `AssertNever`
 * only accepts a `never` argument, so instantiating it with a non-empty
 * `MissingDataVersionKeys` is TS2344 at this declaration, not a value an empty
 * array can vacuously satisfy — the failure mode an earlier version of this
 * check had. Exported (never imported) only so `noUnusedLocals` does not
 * flag the check itself as dead code.
 */
type MissingDataVersionKeys = Exclude<keyof DataVersions, (typeof DATA_VERSION_KEYS)[number]>
type AssertNever<T extends never> = T
export type DataVersionKeysExhaustive = AssertNever<MissingDataVersionKeys>

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
   * (the connection is still open and still delivering — a document this
   * channel's guard rejects is a server that changed the shape of
   * `current_data_versions()`, which fails the polling sibling's consumers
   * identically, so it is not evidence this connection is the broken part).
   * Both would hand the caller a disconnection that never ends.
   *
   * The cause is deliberately not passed on — the caller's answer to either is
   * the same (fall back to polling and say so once), console logging is banned
   * by the E2E console guard, and a cause with nowhere to go is a parameter
   * that reads as if it were used.
   */
  onDisconnect: () => void
}

/** Hold the stream open until `signal` aborts, reporting every document. */
export function runDataVersionsStream({
  signal,
  onDataVersions,
  onStreamOpen,
  onDisconnect,
}: DataVersionsStreamHandlers): Promise<void> {
  return runEventStream({
    path: STREAM_PATH,
    eventName: DATA_VERSIONS_EVENT,
    isEvent: isDataVersions,
    signal,
    onEvent: onDataVersions,
    onStreamOpen,
    onDisconnect,
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
