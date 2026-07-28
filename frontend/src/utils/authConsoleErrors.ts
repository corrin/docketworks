export type CapturedBrowserError = {
  kind: 'console' | 'pageerror'
  text: string
  capturedAt: number
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
export const UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR =
  'Failed to load resource: the server responded with a status of 401'

const SESSION_CHECK_CONSOLE_WINDOW_MS = 5000

export function isUnauthenticatedSessionCheckResponse(event: AuthResponseEvent): boolean {
  return event.pathname === LOGIN_ME_PATH && event.method === 'GET' && event.status === 401
}

// Endpoints where a 401 is the answer, not a symptom: it means the credentials
// were rejected, which must never be allowed away.
const AUTH_ENDPOINT_PATHS = ['/api/accounts/token/', '/api/accounts/token/refresh/']

// Everywhere else, a 401 during an open login window is the app racing its own
// auth cookie: components already mounted fire their loads before login
// completes, so a whole burst (kanban columns, staff list, categories,
// session-replay chunks) 401s together. Each logs a browser "Failed to load
// resource" the app cannot suppress. Recording only the /me check left the rest
// unconsumable, failing whichever test happened to be running.
export function isExpectedPreAuthResponse(event: AuthResponseEvent): boolean {
  return event.status === 401 && !AUTH_ENDPOINT_PATHS.includes(event.pathname)
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
      loginWindowDepth = Math.max(loginWindowDepth - 1, 0)
    }
  }

  const recordResponse = (event: AuthResponseEvent): void => {
    if (loginWindowDepth === 0) return
    if (!isExpectedPreAuthResponse(event)) return
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
