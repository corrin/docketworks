import { describe, expect, it } from 'vitest'
import {
  createLoginSessionCheckConsoleAllowance,
  isUnauthenticatedSessionCheckResponse,
  LOGIN_ME_PATH,
  UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR,
  type CapturedBrowserError,
} from '../../../tests/fixtures/auth-console-errors'

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
