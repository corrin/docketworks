/**
 * @vitest-environment jsdom
 *
 * Capture is browser code — window.location, navigator and the flush timer —
 * so it needs a DOM even though this file carries no JSX.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { flushSessionReplay, startSessionReplay, stopSessionReplay } from './sessionReplayService'
import { setSessionReplayId } from './replayId'

interface ChunkBody {
  sequence: number
  events_json: string
}

const chunksCreate = vi.fn<(options: { body: ChunkBody }) => Promise<unknown>>()
const recordingsCreate = vi.fn()
const emitted: ((event: { type: number; timestamp: number; data?: string }) => void)[] = []

vi.mock('@/api', () => ({
  isApiErrorStatus: (error: unknown, status: number) =>
    typeof error === 'object' && error !== null && (error as { status?: number }).status === status,
  sessionReplayFrontendErrorsCreate: vi.fn(),
  sessionReplayRecordingChunksCreate: (options: { body: ChunkBody }) => chunksCreate(options),
  sessionReplayRecordingsCreate: (...args: unknown[]) => recordingsCreate(...args),
}))

vi.mock('@rrweb/record', () => ({
  record: (options: {
    emit: (event: { type: number; timestamp: number; data?: string }) => void
  }) => {
    emitted.push(options.emit)
    return () => {}
  },
}))

function apiError(status: number): { status: number } {
  return { status }
}

/** The body of one chunk upload; throws rather than returning undefined so a
    missing call fails as "no upload happened", not as a confusing type error. */
function chunkBody(callIndex: number): ChunkBody {
  const call = chunksCreate.mock.calls[callIndex]
  if (!call) throw new Error(`Expected a chunk upload at call ${callIndex}`)
  return call[0].body
}

/** The timestamps a chunk carried, narrowed rather than asserted so a
    malformed upload fails as itself instead of as a later comparison. */
function uploadedTimestamps(eventsJson: string): number[] {
  const parsed: unknown = JSON.parse(eventsJson)
  if (!Array.isArray(parsed)) throw new Error('a chunk must upload a JSON array')
  return parsed.map((event: unknown) => {
    if (
      typeof event !== 'object' ||
      event === null ||
      !('timestamp' in event) ||
      typeof event.timestamp !== 'number'
    ) {
      throw new Error('every uploaded event must carry a numeric timestamp')
    }
    return event.timestamp
  })
}

/** Buffer one event, then flush it. */
async function captureAndFlush(): Promise<void> {
  emitted[emitted.length - 1]?.({ type: 3, timestamp: Date.now() })
  await flushSessionReplay()
}

describe('session replay uploads', () => {
  beforeEach(async () => {
    // The capture service holds module state (the recorder handle, the flush
    // timer, the sequence). Without a real stop, startSessionReplay below
    // early-returns and the next test records against the previous recorder.
    await stopSessionReplay()
    vi.clearAllMocks()
    emitted.length = 0
    setSessionReplayId(null)
    window.localStorage.clear()
    recordingsCreate.mockResolvedValue({ data: { id: 'recording-1' } })
    chunksCreate.mockResolvedValue({ data: {} })
    await startSessionReplay()
  })

  it('numbers chunks consecutively so playback can order them', async () => {
    await captureAndFlush()
    await captureAndFlush()

    expect(chunkBody(0).sequence).toBe(0)
    expect(chunkBody(1).sequence).toBe(1)
  })

  // A 409 means the server already has that chunk. Resending it would 409
  // forever and stall the recording at one sequence number.
  it('advances past a chunk the server already stored', async () => {
    chunksCreate.mockRejectedValueOnce(apiError(409))
    await captureAndFlush()
    await captureAndFlush()

    expect(chunkBody(1).sequence).toBe(1)
  })

  // The events must go back at the FRONT of the buffer: behind later events
  // they would replay out of order, which is worse than losing them.
  it('retries a transient failure without losing or reordering events', async () => {
    chunksCreate.mockRejectedValueOnce(apiError(503))
    await captureAndFlush()
    expect(chunksCreate).toHaveBeenCalledTimes(1)

    await captureAndFlush()
    const retried = chunkBody(1)
    expect(retried.sequence).toBe(0)
    expect(JSON.parse(retried.events_json)).toHaveLength(2)
  })

  // Django refuses a body over DATA_UPLOAD_MAX_MEMORY_SIZE before the view
  // runs, and the 500 that follows is neither a conflict nor terminal — so an
  // oversized chunk went back on the front of the buffer and every later flush
  // resent it, larger each time, for the life of the session. Bounding the
  // upload by size is what keeps one busy interval from ending capture.
  it('splits a burst too big for one request instead of resending it forever', async () => {
    const emit = emitted[emitted.length - 1]
    if (!emit) throw new Error('the recorder was never started')
    const bulky = 'x'.repeat(400_000)
    for (let index = 0; index < 6; index += 1) {
      emit({ type: 3, timestamp: index, data: bulky })
    }

    await flushSessionReplay()

    expect(chunksCreate.mock.calls.length).toBeGreaterThan(1)
    for (const [options] of chunksCreate.mock.calls) {
      expect(options.body.events_json.length).toBeLessThanOrEqual(1_000_000)
    }
    // Split, not dropped: every event reaches the server exactly once, in order.
    const uploaded = chunksCreate.mock.calls.flatMap(([options]) =>
      uploadedTimestamps(options.body.events_json),
    )
    expect(uploaded).toEqual([0, 1, 2, 3, 4, 5])
    expect(chunksCreate.mock.calls.map(([options]) => options.body.sequence)).toEqual([0, 1, 2])
  })

  it.each([401, 403, 404])('stops recording after a terminal %i', async (status) => {
    chunksCreate.mockRejectedValueOnce(apiError(status))
    await captureAndFlush()

    await captureAndFlush()
    expect(chunksCreate).toHaveBeenCalledTimes(1)
  })
})

describe('session replay start', () => {
  beforeEach(async () => {
    await stopSessionReplay()
    vi.clearAllMocks()
    emitted.length = 0
    setSessionReplayId(null)
    window.localStorage.clear()
  })

  // Callers start capture as a floating promise, and this module installs the
  // unhandledrejection listener that reports uncaught errors — so a rejection
  // here would be caught by our own reporter and filed as a frontend error row
  // on every authenticated page load. An instance with recording switched off
  // must be silent, not self-reporting.
  it('is silent when the company has recording switched off', async () => {
    recordingsCreate.mockRejectedValue(apiError(409))

    await expect(startSessionReplay()).resolves.toBeUndefined()
    expect(emitted).toHaveLength(0)
  })

  // A refusal is an answer; a broken server is not, and swallowing it would
  // mean capture silently never runs with nothing to show why.
  it('surfaces a server failure rather than swallowing it', async () => {
    recordingsCreate.mockRejectedValue(apiError(500))

    await expect(startSessionReplay()).rejects.toStrictEqual(apiError(500))
  })
})
