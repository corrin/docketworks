import { record } from '@rrweb/record'
import type { eventWithTime } from '@rrweb/types'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import {
  getSessionReplayId as getCurrentSessionReplayId,
  setSessionReplayId,
} from '@/services/sessionReplayState'

type StopRecording = () => void

const FLUSH_INTERVAL_MS = 10_000

let stopRecording: StopRecording | null = null
let flushTimer: number | null = null
let sequence = 0
let bufferedEvents: eventWithTime[] = []
let isFlushing = false

function currentPath(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
}

function currentJobId(): string | null {
  const match = window.location.pathname.match(/^\/jobs\/([^/]+)/)
  if (!match) return null
  if (match[1] === 'create') return null
  return match[1] ?? null
}

function viewport() {
  return {
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
  }
}

export async function startSessionReplay(): Promise<void> {
  if (getCurrentSessionReplayId() || stopRecording) return

  const recording = await api.session_replay_recordings_create({
    initial_path: currentPath(),
    job_id: currentJobId(),
    ...viewport(),
  })
  setSessionReplayId(recording.id)

  const stop = record<eventWithTime>({
    emit(event) {
      bufferedEvents.push(event)
    },
    // Full-fidelity capture is intentional for staff-only installs with recording consent.
    checkoutEveryNms: 5 * 60 * 1000,
    recordCanvas: false,
    collectFonts: false,
    inlineImages: false,
    sampling: {
      mousemove: 200,
      mouseInteraction: true,
      scroll: 150,
      media: 800,
      input: 'last',
    },
  })

  if (!stop) {
    setSessionReplayId(null)
    throw new Error('rrweb recorder did not start')
  }

  stopRecording = stop
  flushTimer = window.setInterval(() => {
    flushSessionReplay().catch((error) => {
      debugLog('[sessionReplay] periodic flush failed:', error)
    })
  }, FLUSH_INTERVAL_MS)
}

export async function flushSessionReplay(): Promise<void> {
  const recordingId = getCurrentSessionReplayId()
  if (!recordingId) return
  if (isFlushing) return
  if (bufferedEvents.length === 0) return

  const events = bufferedEvents
  bufferedEvents = []
  isFlushing = true
  try {
    const first = events[0]
    const last = events[events.length - 1]
    await api.session_replay_recording_chunks_create(
      {
        sequence,
        events_json: JSON.stringify(events),
        first_event_timestamp_ms: first.timestamp,
        last_event_timestamp_ms: last.timestamp,
        path: currentPath(),
        job_id: currentJobId(),
        ...viewport(),
      },
      {
        params: { id: recordingId },
      },
    )
    sequence += 1
  } catch (error) {
    bufferedEvents = [...events, ...bufferedEvents]
    throw error
  } finally {
    isFlushing = false
  }
}

export async function stopSessionReplay(): Promise<void> {
  if (flushTimer !== null) {
    window.clearInterval(flushTimer)
    flushTimer = null
  }
  if (stopRecording) {
    stopRecording()
    stopRecording = null
  }
  try {
    await flushSessionReplay()
  } finally {
    setSessionReplayId(null)
    sequence = 0
    bufferedEvents = []
  }
}

export async function reportFrontendError(
  error: ErrorEvent | PromiseRejectionEvent,
): Promise<void> {
  const reason = 'reason' in error ? error.reason : error.error
  const message =
    reason instanceof Error
      ? reason.message
      : error instanceof ErrorEvent
        ? error.message
        : String(reason)
  const stack = reason instanceof Error ? reason.stack : undefined

  await flushSessionReplay().catch((flushError) => {
    debugLog('[sessionReplay] flush before frontend error failed:', flushError)
  })

  await api.session_replay_frontend_errors_create({
    message,
    stack,
    path: currentPath(),
    component: 'window',
    session_replay_id: getCurrentSessionReplayId(),
  })
}
