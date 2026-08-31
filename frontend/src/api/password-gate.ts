import type { AxiosInstance } from 'axios'

import { isPasswordChangeRequiredError } from './error-message'

/** Fable: hard navigation, not router state — the typed 403 can surface from
 * any stale tab or background query, contexts with no router in scope. */
export function hardNavigateToChangePassword(): void {
  if (window.location.pathname !== '/change-password') {
    window.location.assign('/change-password')
  }
}

/**
 * Install the response interceptor that walks a flagged session to the
 * change-password screen. The route guards cover ordinary navigation; this
 * covers sessions flagged AFTER they loaded the app (an admin forcing a
 * change mid-session), whose next request 403s with the typed code.
 * Always rethrows — features still see their request fail.
 */
export function installPasswordGate(
  instance: AxiosInstance,
  navigate: () => void = hardNavigateToChangePassword,
): void {
  instance.interceptors.response.use(undefined, (error: unknown) => {
    if (isPasswordChangeRequiredError(error)) {
      navigate()
    }
    throw error
  })
}
