import { describe, expect, it } from 'vitest'
import {
  createLoginSessionCheckConsoleAllowance,
  isLoginCompletionResponse,
  isUnauthenticatedSessionCheckResponse,
  LOGIN_ME_PATH,
  UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR,
  type AuthResponseEvent,
  type CapturedBrowserError,
} from '@/utils/authConsoleErrors'

function console401(capturedAt: number): CapturedBrowserError {
  return {
    kind: 'console',
    text: UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR,
    capturedAt,
  }
}

describe('auth E2E console allowance', () => {
  it('recognizes only unauthenticated session-check responses', () => {
    expect(
      isUnauthenticatedSessionCheckResponse({
        pathname: LOGIN_ME_PATH,
        method: 'GET',
        status: 401,
      }),
    ).toBe(true)
    expect(
      isUnauthenticatedSessionCheckResponse({
        pathname: LOGIN_ME_PATH,
        method: 'POST',
        status: 401,
      }),
    ).toBe(false)
    expect(
      isUnauthenticatedSessionCheckResponse({
        pathname: '/api/accounts/token/',
        method: 'GET',
        status: 401,
      }),
    ).toBe(false)
    expect(
      isUnauthenticatedSessionCheckResponse({
        pathname: LOGIN_ME_PATH,
        method: 'GET',
        status: 403,
      }),
    ).toBe(false)
  })

  it('consumes one matching console 401 for one matching response during login', () => {
    const allowance = createLoginSessionCheckConsoleAllowance(() => 1000)
    const stop = allowance.startLoginWindow()

    allowance.recordResponse({ pathname: LOGIN_ME_PATH, method: 'GET', status: 401 })
    stop()

    expect(allowance.consumeIfExpected(console401(1100))).toBe(true)
    expect(allowance.consumeIfExpected(console401(1200))).toBe(false)
  })

  it('does not consume matching response outside the login window', () => {
    const allowance = createLoginSessionCheckConsoleAllowance(() => 1000)

    allowance.recordResponse({ pathname: LOGIN_ME_PATH, method: 'GET', status: 401 })

    expect(allowance.consumeIfExpected(console401(1000))).toBe(false)
  })

  it('does not consume unrelated 401 console errors', () => {
    const allowance = createLoginSessionCheckConsoleAllowance(() => 1000)
    const stop = allowance.startLoginWindow()

    allowance.recordResponse({
      pathname: '/api/accounts/token/',
      method: 'POST',
      status: 401,
    })
    stop()

    expect(allowance.consumeIfExpected(console401(1000))).toBe(false)
  })

  it('does not consume stale console errors outside the timing window', () => {
    const allowance = createLoginSessionCheckConsoleAllowance(() => 1000)
    const stop = allowance.startLoginWindow()

    allowance.recordResponse({ pathname: LOGIN_ME_PATH, method: 'GET', status: 401 })
    stop()

    expect(allowance.consumeIfExpected(console401(7000))).toBe(false)
  })

  it('login /me waiter selects the authenticated response over the expected pre-auth 401', () => {
    // Order the E2E login fixture actually observes: the app's unauthenticated session-check
    // 401 can land in the login window before the authenticated 200. The waiter must resolve
    // on the 200, never the 401 — otherwise login flakes (~1/35) on slow hydration.
    const preAuth401: AuthResponseEvent = { pathname: LOGIN_ME_PATH, method: 'GET', status: 401 }
    const authenticated200: AuthResponseEvent = {
      pathname: LOGIN_ME_PATH,
      method: 'GET',
      status: 200,
    }

    expect(isLoginCompletionResponse(preAuth401)).toBe(false)
    expect(isLoginCompletionResponse(authenticated200)).toBe(true)
    // The waiter takes the first accepted response from the observed sequence.
    expect([preAuth401, authenticated200].filter(isLoginCompletionResponse)).toEqual([
      authenticated200,
    ])
  })

  it('login /me waiter ignores non-/me responses', () => {
    expect(
      isLoginCompletionResponse({ pathname: '/api/accounts/token/', method: 'POST', status: 200 }),
    ).toBe(false)
  })

  it.each([
    { pathname: '/api/process/categories/', method: 'GET' },
    { pathname: '/api/job/jobs/fetch-by-column/draft/', method: 'GET' },
    { pathname: '/api/accounts/staff/all/', method: 'GET' },
    { pathname: '/api/session-replays/recordings/', method: 'POST' },
  ])('does not consume a 401 from $pathname during login', ({ pathname, method }) => {
    const allowance = createLoginSessionCheckConsoleAllowance(() => 1000)
    const stop = allowance.startLoginWindow()

    allowance.recordResponse({ pathname, method, status: 401 })
    stop()

    expect(allowance.consumeIfExpected(console401(1000))).toBe(false)
  })

  it('never consumes a rejected login, even inside the login window', () => {
    // A 401 from the token endpoint means the credentials were refused. That is
    // the answer, not a symptom, and must always fail the suite.
    const allowance = createLoginSessionCheckConsoleAllowance(() => 1000)
    const stop = allowance.startLoginWindow()

    allowance.recordResponse({
      pathname: '/api/accounts/token/',
      method: 'POST',
      status: 401,
    })
    allowance.recordResponse({
      pathname: '/api/accounts/token/refresh/',
      method: 'POST',
      status: 401,
    })
    stop()

    expect(allowance.consumeIfExpected(console401(1000))).toBe(false)
  })

  it('does not consume a burst that lands outside any login window', () => {
    const allowance = createLoginSessionCheckConsoleAllowance(() => 1000)

    allowance.recordResponse({
      pathname: '/api/process/categories/',
      method: 'GET',
      status: 401,
    })

    expect(allowance.consumeIfExpected(console401(1000))).toBe(false)
  })

  it('does not consume page errors with the same text', () => {
    const allowance = createLoginSessionCheckConsoleAllowance(() => 1000)
    const stop = allowance.startLoginWindow()

    allowance.recordResponse({ pathname: LOGIN_ME_PATH, method: 'GET', status: 401 })
    stop()

    expect(
      allowance.consumeIfExpected({
        kind: 'pageerror',
        text: UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR,
        capturedAt: 1000,
      }),
    ).toBe(false)
  })
})
