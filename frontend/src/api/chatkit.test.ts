import { afterEach, describe, expect, it, vi } from 'vitest'

const { refresh, navigate } = vi.hoisted(() => ({ refresh: vi.fn(), navigate: vi.fn() }))
vi.mock('./client', () => ({ refreshAccessToken: refresh }))
vi.mock('./password-gate', () => ({ hardNavigateToChangePassword: navigate }))
vi.mock('@/features/shared/session-replay/replayId', () => ({
  getSessionReplayId: () => 'replay-test',
}))

import { quotingChatFetch } from './chatkit'

const origin = 'http://localhost:4173'
const url = `${origin}/api/job/jobs/job-1/quote-chat/`
const authResponse = () =>
  new Response(
    JSON.stringify({ code: 'authentication_required', detail: 'Sign in', error_id: null }),
    { status: 401, headers: { 'Content-Type': 'application/json' } },
  )

function setup() {
  vi.stubGlobal('window', { location: { origin } })
  const fetch = vi.fn<typeof globalThis.fetch>()
  vi.stubGlobal('fetch', fetch)
  return fetch
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetAllMocks()
})

describe('ChatKit transport', () => {
  it('refreshes an expired session and replays the same body with CSRF and replay headers', async () => {
    const fetch = setup()
    fetch
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(new Response('data: hello\n\n'))
    const body = JSON.stringify({ type: 'threads.list', params: {} })
    const response = await quotingChatFetch('job-1', 'csrf-token')(url, { method: 'POST', body })
    expect(await response.text()).toBe('data: hello\n\n')
    expect(refresh).toHaveBeenCalledOnce()
    expect(fetch).toHaveBeenCalledTimes(2)
    await Promise.all(
      fetch.mock.calls.map(async ([request]) => {
        expect(request).toBeInstanceOf(Request)
        if (!(request instanceof Request)) throw new Error('Expected authenticated request')
        expect(await request.text()).toBe(body)
        expect(request.headers.get('X-CSRFToken')).toBe('csrf-token')
        expect(request.headers.get('X-Session-Replay-Id')).toBe('replay-test')
        expect(request.credentials).toBe('same-origin')
      }),
    )
  })

  it('does not resend a message cancelled during token refresh', async () => {
    const fetch = setup()
    const controller = new AbortController()
    fetch.mockResolvedValueOnce(authResponse())
    refresh.mockImplementationOnce(async () => controller.abort())
    await expect(
      quotingChatFetch('job-1', 'csrf-token')(url, {
        method: 'POST',
        body: '{}',
        signal: controller.signal,
      }),
    ).rejects.toThrow()
    expect(fetch).toHaveBeenCalledOnce()
  })

  it('rejects an unexpected destination before sending credentials', async () => {
    const fetch = setup()
    await expect(quotingChatFetch('job-1', 'csrf-token')('https://example.com/')).rejects.toThrow(
      'unexpected endpoint',
    )
    expect(fetch).not.toHaveBeenCalled()
  })

  it('preserves a CSRF refusal and follows the existing password-reset gate', async () => {
    const fetch = setup()
    const forbidden = new Response('<html>CSRF rejected</html>', {
      status: 403,
      headers: { 'Content-Type': 'text/html' },
    })
    fetch.mockResolvedValueOnce(forbidden)
    expect(await quotingChatFetch('job-1', 'csrf-token')(url)).toBe(forbidden)
    fetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ code: 'password_change_required' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await quotingChatFetch('job-1', 'csrf-token')(url)
    expect(navigate).toHaveBeenCalledOnce()
    expect(refresh).not.toHaveBeenCalled()
  })
})
