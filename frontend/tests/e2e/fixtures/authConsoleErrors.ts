export type CapturedBrowserError = {
  kind: 'console' | 'pageerror'
  text: string
  capturedAt: number
  /** The resource a browser-emitted network line names; absent for app console output. */
  url?: string
}

export type ResourceResponseEvent = {
  url: string
  status: number
  observedAt: number
}

export const NETWORK_FAILURE_CONSOLE_PREFIX = 'Failed to load resource: net::'

/**
 * A `net::ERR_*` console line is the browser reporting a connection that died,
 * not the app reporting anything; when the same URL then loads, the app has
 * recovered on its own (a query retried, a chunk fetched after reload) and has
 * nothing to toast or throw. The allowance is per URL and only for a success
 * observed AFTER the failure, so a resource that never loads still fails the test.
 */
export function createRecoveredLoadAllowance(): {
  recordResponse: (event: ResourceResponseEvent) => void
  isRecovered: (error: CapturedBrowserError) => boolean
} {
  const successes: ResourceResponseEvent[] = []
  return {
    recordResponse: (event) => {
      if (event.status < 400) successes.push(event)
    },
    isRecovered: (error) =>
      error.kind === 'console' &&
      error.text.startsWith(NETWORK_FAILURE_CONSOLE_PREFIX) &&
      error.url !== undefined &&
      successes.some((s) => s.url === error.url && s.observedAt >= error.capturedAt),
  }
}

export type AuthResponseEvent = {
  method: string
  pathname: string
  status: number
}

type AllowedSessionCheck = {
  observedAt: number
  consumed: boolean
}

export const LOGIN_ME_PATH = '/api/accounts/me/'
export const LOGIN_REFRESH_PATH = '/api/accounts/token/refresh/'
export const UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR =
  'Failed to load resource: the server responded with a status of 401'

const SESSION_CHECK_CONSOLE_WINDOW_MS = 5000

export function isUnauthenticatedSessionCheckResponse(event: AuthResponseEvent): boolean {
  return event.pathname === LOGIN_ME_PATH && event.method === 'GET' && event.status === 401
}

function isExpectedLoginRecoveryResponse(event: AuthResponseEvent): boolean {
  return (
    isUnauthenticatedSessionCheckResponse(event) ||
    (event.pathname === LOGIN_REFRESH_PATH && event.method === 'POST' && event.status === 401)
  )
}

// The E2E login flow waits for the authenticated GET /me to confirm login completed. During
// the same login window the app also fires an expected unauthenticated GET /me → 401 (see
// isUnauthenticatedSessionCheckResponse); the waiter must skip that and resolve only on the
// authenticated response, or it flakes when the 401 lands after the waiter is registered.
export function isLoginCompletionResponse(event: AuthResponseEvent): boolean {
  return (
    event.pathname === LOGIN_ME_PATH &&
    event.method === 'GET' &&
    !isUnauthenticatedSessionCheckResponse(event)
  )
}

export function createLoginSessionCheckConsoleAllowance(now: () => number = Date.now): {
  startLoginWindow: () => () => void
  recordResponse: (event: AuthResponseEvent) => void
  consumeIfExpected: (error: CapturedBrowserError) => boolean
} {
  let loginWindowDepth = 0
  const allowedSessionChecks: AllowedSessionCheck[] = []

  const startLoginWindow = (): (() => void) => {
    loginWindowDepth += 1
    let stopped = false
    return () => {
      if (stopped) return
      stopped = true
      loginWindowDepth -= 1
    }
  }

  const recordResponse = (event: AuthResponseEvent): void => {
    if (loginWindowDepth === 0) return
    if (!isExpectedLoginRecoveryResponse(event)) return
    allowedSessionChecks.push({ observedAt: now(), consumed: false })
  }

  const consumeIfExpected = (error: CapturedBrowserError): boolean => {
    if (
      error.kind !== 'console' ||
      !error.text.includes(UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR)
    ) {
      return false
    }

    const match = allowedSessionChecks.find(
      (candidate) =>
        !candidate.consumed &&
        Math.abs(error.capturedAt - candidate.observedAt) <= SESSION_CHECK_CONSOLE_WINDOW_MS,
    )
    if (!match) return false

    match.consumed = true
    return true
  }

  return {
    startLoginWindow,
    recordResponse,
    consumeIfExpected,
  }
}
