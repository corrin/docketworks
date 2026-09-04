/**
 * Bind capture to the authenticated session's lifetime.
 *
 * Recording starts once the user is authenticated and stops on logout, so a
 * recording always has an owner to file it against. The flush on
 * visibilitychange and pagehide is what saves the last ten seconds before a
 * user closes the tab — usually the ten seconds a bug report is about.
 */
import { useEffect } from 'react'

import {
  flushSessionReplay,
  reportFrontendError,
  startSessionReplay,
  stopSessionReplay,
} from './sessionReplayService'

function errorDetail(event: ErrorEvent | PromiseRejectionEvent): {
  message: string
  stack: string | null
} {
  if ('reason' in event) {
    const reason: unknown = event.reason
    if (reason instanceof Error) return { message: reason.message, stack: reason.stack ?? null }
    return { message: String(reason), stack: null }
  }
  return {
    message: event.message,
    stack: event.error instanceof Error ? (event.error.stack ?? null) : null,
  }
}

export function useSessionReplay(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return undefined

    void startSessionReplay()

    const flushIfHidden = (): void => {
      if (document.visibilityState === 'hidden') void flushSessionReplay()
    }
    const flushNow = (): void => {
      void flushSessionReplay()
    }
    const captureError = (event: ErrorEvent | PromiseRejectionEvent): void => {
      const { message, stack } = errorDetail(event)
      void reportFrontendError(message, stack)
    }

    document.addEventListener('visibilitychange', flushIfHidden)
    // pagehide, not beforeunload: beforeunload does not fire on mobile Safari
    // when the tab is discarded, which is exactly when the buffer is lost.
    window.addEventListener('pagehide', flushNow)
    window.addEventListener('error', captureError)
    window.addEventListener('unhandledrejection', captureError)

    return () => {
      document.removeEventListener('visibilitychange', flushIfHidden)
      window.removeEventListener('pagehide', flushNow)
      window.removeEventListener('error', captureError)
      window.removeEventListener('unhandledrejection', captureError)
      // Opus: stop, not merely flush. A flush leaves rrweb's observers, the 10s
      // timer and the recording id alive past the authenticated layout, so
      // capture continues over the login screen and the next startSessionReplay
      // finds an id already set and early-returns — appending one person's
      // session to the previous person's recording. Only an upload's eventual
      // 401 ends that, which is far too late for whose screen is in it.
      void stopSessionReplay()
    }
  }, [enabled])
}
