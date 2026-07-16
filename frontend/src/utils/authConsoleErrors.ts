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
    if (!isUnauthenticatedSessionCheckResponse(event)) return
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
