/**
 * rrweb capture: buffer events, flush them to the server as ordered chunks.
 *
 * The upload rules here are the parts that took v1 several iterations to get
 * right, and they are about not losing a session rather than about speed:
 * a retryable failure puts the events back at the FRONT of the buffer, and a
 * 409 means the chunk already landed, so the sequence advances and recording
 * continues rather than the whole recording being discarded.
 */
import { record } from '@rrweb/record'
import type { eventWithTime } from '@rrweb/types'

import {
  isApiErrorStatus,
  sessionReplayFrontendErrorsCreate,
  sessionReplayRecordingChunksCreate,
  sessionReplayRecordingsCreate,
} from '@/api'

import { getSessionReplayId, setSessionReplayId } from './replayId'

type StopRecording = () => void

const FLUSH_INTERVAL_MS = 10_000
/**
 * Django refuses a body over DATA_UPLOAD_MAX_MEMORY_SIZE (2.5 MB by default)
 * before any view runs, and a chunk used to be bounded only by the 10s timer —
 * so one burst of DOM churn buffered more than that in a single interval and
 * the upload 500'd. The lost chunk was the smaller half of it: a 500 is
 * neither a conflict nor a terminal failure, so the events went back on the
 * front of the buffer and every later flush re-sent them plus everything
 * since, larger each time, once per 10s for the life of the session.
 *
 * Well under the server's limit because this counts UTF-16 code units while
 * the limit counts bytes, so a recording full of non-ASCII text measures
 * smaller here than on the wire; the headroom absorbs that rather than a
 * per-event byte count nobody can afford to compute on every flush.
 */
const MAX_CHUNK_CHARS = 1_000_000
const E2E_DISABLE_KEY = 'e2e:disable-session-replay'

let stopRecording: StopRecording | null = null
let flushTimer: ReturnType<typeof setInterval> | null = null
let sequence = 0
let buffered: eventWithTime[] = []
let isFlushing = false

/**
 * The E2E suite drives a real browser over ngrok. Recording every spec would
 * push chunk uploads through the same tunnel the run is already bottlenecked
 * on, so capture is off there — and only there.
 */
function disabledForE2E(): boolean {
  const isPlaywrightOverNgrok =
    navigator.webdriver && window.location.hostname.endsWith('.ngrok-free.app')
  try {
    return (
      import.meta.env.DEV &&
      (isPlaywrightOverNgrok || window.localStorage.getItem(E2E_DISABLE_KEY) === 'true')
    )
  } catch {
    // A browser configured to block site data throws on localStorage access.
    // Recording is the safe default; only the explicit opt-out disables it.
    return import.meta.env.DEV && isPlaywrightOverNgrok
  }
}

/** 401/403/404 mean this recording can never accept another chunk. */
function isTerminalUploadFailure(error: unknown): boolean {
  return (
    isApiErrorStatus(error, 401) || isApiErrorStatus(error, 403) || isApiErrorStatus(error, 404)
  )
}

function currentPath(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
}

/** Tag a recording with the job being viewed, so a bug report can find it. */
function currentJobId(): string | null {
  const match = window.location.pathname.match(/^\/jobs\/([^/]+)/)
  if (!match || match[1] === 'create') return null
  return match[1] ?? null
}

function viewport(): { viewport_width: number; viewport_height: number } {
  return { viewport_width: window.innerWidth, viewport_height: window.innerHeight }
}

function discardRecordingState(): void {
  if (flushTimer !== null) {
    clearInterval(flushTimer)
    flushTimer = null
  }
  if (stopRecording) {
    stopRecording()
    stopRecording = null
  }
  setSessionReplayId(null)
  sequence = 0
  buffered = []
}

/**
 * Take the longest run of buffered events that fits in one upload, removing
 * it from the buffer. Always at least one event: an event bigger than the cap
 * cannot be split, and holding it back would stall every event behind it
 * forever.
 */
function takeChunk(): eventWithTime[] {
  const taken: eventWithTime[] = []
  let size = 2
  for (const event of buffered) {
    const eventSize = JSON.stringify(event).length + 1
    if (taken.length > 0 && size + eventSize > MAX_CHUNK_CHARS) break
    taken.push(event)
    size += eventSize
  }
  buffered = buffered.slice(taken.length)
  return taken
}

export async function flushSessionReplay(): Promise<void> {
  const recordingId = getSessionReplayId()
  if (!recordingId || isFlushing || buffered.length === 0) return

  isFlushing = true
  try {
    // Drains in as many uploads as the backlog needs rather than one per
    // interval: after a tab has been hidden for a while the buffer holds
    // minutes of events, and one chunk per 10s would never catch up.
    while (buffered.length > 0) {
      const events = takeChunk()
      try {
        // The rule's Promise.all advice is wrong for this loop: chunks carry
        // an ordered `sequence` that only advances on a success, and the
        // failure branches below decide whether the REST of the backlog is
        // still sendable. Uploading in parallel would number them by
        // completion order and keep sending after a terminal refusal.
        // oxlint-disable-next-line no-await-in-loop
        await sessionReplayRecordingChunksCreate({
          path: { recording_id: recordingId },
          body: {
            sequence,
            events_json: JSON.stringify(events),
            first_event_timestamp_ms: events[0]?.timestamp ?? 0,
            last_event_timestamp_ms: events[events.length - 1]?.timestamp ?? 0,
            path: currentPath(),
            job_id: currentJobId(),
            ...viewport(),
          },
          throwOnError: true,
        })
        sequence += 1
      } catch (error) {
        if (isApiErrorStatus(error, 409)) {
          // The chunk is already stored. Re-sending it would 409 forever, and
          // these events are on the server, so advance past them.
          sequence += 1
        } else if (isTerminalUploadFailure(error)) {
          discardRecordingState()
          return
        } else {
          // Transient: put them back at the FRONT, ahead of whatever rrweb has
          // emitted since, or the replay would play back out of order. The
          // rest of the backlog waits for the next flush rather than pushing
          // past them into the same disorder.
          buffered = [...events, ...buffered]
          return
        }
      }
    }
  } finally {
    isFlushing = false
  }
}

export async function startSessionReplay(): Promise<void> {
  if (disabledForE2E()) return
  if (getSessionReplayId() || stopRecording) return

  let created
  try {
    created = await sessionReplayRecordingsCreate({
      body: { initial_path: currentPath(), job_id: currentJobId(), ...viewport() },
      throwOnError: true,
    })
  } catch (error) {
    // 409 is the company toggle: this instance does not record, which is an
    // answer rather than a fault. Converted here rather than left to reject,
    // because the caller starts capture with `void startSessionReplay()` and
    // this module installs the `unhandledrejection` listener that reports
    // uncaught errors — so a rejection here is caught by our own reporter and
    // filed as a frontend error row on EVERY authenticated page load. Turning
    // the feature off would generate an error per page view.
    if (isApiErrorStatus(error, 409)) return
    throw error
  }
  setSessionReplayId(created.data.id)

  stopRecording =
    record({
      emit(event) {
        buffered.push(event)
      },
      // Full-fidelity capture is deliberate: these are staff-only installs,
      // the recordings are superuser-visible only, and a masked replay of a
      // pricing bug shows none of the numbers that caused it.
      checkoutEveryNms: 5 * 60_000,
      recordCanvas: false,
      collectFonts: false,
      inlineImages: false,
      // Never record the replay player. rrweb walks into same-origin iframes,
      // and the player rebuilds a whole recorded page inside one — so without
      // this, watching a replay re-records it: a single mutation adding 5,642
      // nodes and over 1MB was how the E2E wire-size guard caught it. Worse
      // than the size, the viewer's own recording would then CONTAIN the
      // session they were watching, so one person's screen leaks into
      // another's recording.
      blockSelector: '[data-rrweb-block]',
      sampling: { mousemove: 200, scroll: 150, media: 800, input: 'last' },
    }) ?? null

  flushTimer = setInterval(() => {
    void flushSessionReplay()
  }, FLUSH_INTERVAL_MS)
}

export async function stopSessionReplay(): Promise<void> {
  await flushSessionReplay()
  discardRecordingState()
}

/**
 * File an uncaught browser error against the replay it happened in.
 *
 * The flush comes first so the events leading up to the failure are on the
 * server before the error row that points at them — an error linked to a
 * recording that stops seconds early is the case this ordering avoids.
 */
export async function reportFrontendError(message: string, stack: string | null): Promise<void> {
  await flushSessionReplay()
  await sessionReplayFrontendErrorsCreate({
    body: {
      message,
      stack,
      path: currentPath(),
      session_replay_id: getSessionReplayId(),
    },
  })
}
