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

export async function flushSessionReplay(): Promise<void> {
  const recordingId = getSessionReplayId()
  if (!recordingId || isFlushing || buffered.length === 0) return

  isFlushing = true
  const events = buffered
  buffered = []
  try {
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
    } else {
      // Transient: put them back at the FRONT, ahead of whatever rrweb has
      // emitted since, or the replay would play back out of order.
      buffered = [...events, ...buffered]
    }
  } finally {
    isFlushing = false
  }
}

export async function startSessionReplay(): Promise<void> {
  if (disabledForE2E()) return
  if (getSessionReplayId() || stopRecording) return

  const created = await sessionReplayRecordingsCreate({
    body: { initial_path: currentPath(), job_id: currentJobId(), ...viewport() },
    throwOnError: true,
  })
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
