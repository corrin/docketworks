import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock, recordMock, stopRecordingMock, emitReplayEvent } = vi.hoisted(() => {
  let emit: ((event: { type: number; timestamp: number }) => void) | null = null
  const stop = vi.fn()

  return {
    apiMock: {
      session_replay_recordings_create: vi.fn(),
      session_replay_recording_chunks_create: vi.fn(),
    },
    recordMock: vi.fn((options: { emit: (event: { type: number; timestamp: number }) => void }) => {
      emit = options.emit
      return stop
    }),
    stopRecordingMock: stop,
    emitReplayEvent: (event: { type: number; timestamp: number }) => {
      if (!emit) throw new Error('recorder has not started')
      emit(event)
    },
  }
})

vi.mock('@/api/client', () => ({
  api: apiMock,
}))

vi.mock('@rrweb/record', () => ({
  record: recordMock,
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

describe('sessionReplayService', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    vi.resetModules()
    window.localStorage.clear()
    const state = await import('@/services/sessionReplayState')
    state.setSessionReplayId(null)
    apiMock.session_replay_recordings_create.mockResolvedValue({ id: 'replay-1' })
    apiMock.session_replay_recording_chunks_create.mockResolvedValue({ id: 'chunk-1' })
  })

  it('does not start replay capture when E2E disables it in dev', async () => {
    window.localStorage.setItem('e2e:disable-session-replay', 'true')
    const { startSessionReplay } = await import('@/services/sessionReplayService')

    await startSessionReplay()

    expect(apiMock.session_replay_recordings_create).not.toHaveBeenCalled()
    expect(recordMock).not.toHaveBeenCalled()
  })

  it('drops duplicate chunk uploads and continues with the next sequence', async () => {
    const { startSessionReplay, flushSessionReplay } =
      await import('@/services/sessionReplayService')
    apiMock.session_replay_recording_chunks_create
      .mockRejectedValueOnce({ response: { status: 409 } })
      .mockResolvedValueOnce({ id: 'chunk-2' })

    await startSessionReplay()
    emitReplayEvent({ type: 4, timestamp: 1 })
    await flushSessionReplay()

    emitReplayEvent({ type: 4, timestamp: 2 })
    await flushSessionReplay()

    expect(apiMock.session_replay_recording_chunks_create).toHaveBeenCalledTimes(2)
    expect(apiMock.session_replay_recording_chunks_create.mock.calls[0][0].sequence).toBe(0)
    expect(apiMock.session_replay_recording_chunks_create.mock.calls[1][0].sequence).toBe(1)
    const { getSessionReplayId } = await import('@/services/sessionReplayState')
    expect(getSessionReplayId()).toBe('replay-1')
  })

  it('discards stale replay state after a missing recording response', async () => {
    const { startSessionReplay, flushSessionReplay } =
      await import('@/services/sessionReplayService')
    apiMock.session_replay_recording_chunks_create.mockRejectedValueOnce({
      response: { status: 404 },
    })

    await startSessionReplay()
    emitReplayEvent({ type: 4, timestamp: 1 })
    await flushSessionReplay()
    await flushSessionReplay()

    expect(apiMock.session_replay_recording_chunks_create).toHaveBeenCalledOnce()
    expect(stopRecordingMock).toHaveBeenCalledOnce()
    const { getSessionReplayId } = await import('@/services/sessionReplayState')
    expect(getSessionReplayId()).toBeNull()
  })

  it('keeps retryable upload failures buffered', async () => {
    const { startSessionReplay, flushSessionReplay } =
      await import('@/services/sessionReplayService')
    apiMock.session_replay_recording_chunks_create
      .mockRejectedValueOnce({ response: { status: 500 } })
      .mockResolvedValueOnce({ id: 'chunk-2' })

    await startSessionReplay()
    emitReplayEvent({ type: 4, timestamp: 1 })
    await expect(flushSessionReplay()).rejects.toMatchObject({ response: { status: 500 } })
    await flushSessionReplay()

    expect(apiMock.session_replay_recording_chunks_create).toHaveBeenCalledTimes(2)
    expect(apiMock.session_replay_recording_chunks_create.mock.calls[0][0].sequence).toBe(0)
    expect(apiMock.session_replay_recording_chunks_create.mock.calls[1][0].sequence).toBe(0)
  })
})
