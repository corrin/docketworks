import type { AxiosInstance, InternalAxiosRequestConfig } from 'axios'
import { isAxiosError } from 'axios'

import { isSessionAuthenticationError } from './error-message'

const AUTH_ENDPOINTS = [
  '/api/accounts/token/',
  '/api/accounts/token/refresh/',
  '/api/accounts/logout/',
] as const

interface AuthRetryConfig extends InternalAxiosRequestConfig {
  authRecoveryAttempted?: boolean
}

function isAuthEndpoint(url: string | undefined): boolean {
  if (url === undefined) return false
  try {
    const pathname = new URL(url, 'http://docketworks.invalid').pathname
    return AUTH_ENDPOINTS.some((endpoint) => pathname === endpoint)
  } catch {
    return false
  }
}

function requestWasAborted(config: AuthRetryConfig): boolean {
  return config.signal?.aborted === true
}

/**
 * Install the one access-token recovery path on the shared transport.
 *
 * The backend emits `authentication_required` only before entering a protected
 * operation, so even a non-idempotent request is safe to replay once. A plain
 * domain 401 never carries that code and is returned to its feature unchanged.
 */
export function installAuthRecovery(
  instance: AxiosInstance,
  refreshAccessToken: () => Promise<void>,
): void {
  let refreshInFlight: Promise<void> | null = null

  async function refreshOnce(): Promise<void> {
    if (refreshInFlight !== null) return refreshInFlight
    refreshInFlight = (async () => {
      try {
        await refreshAccessToken()
      } finally {
        refreshInFlight = null
      }
    })()
    return refreshInFlight
  }

  instance.interceptors.response.use(undefined, async (error: unknown) => {
    if (!isSessionAuthenticationError(error) || !isAxiosError(error)) throw error

    const config = error.config as AuthRetryConfig | undefined
    if (
      config === undefined ||
      config.authRecoveryAttempted === true ||
      isAuthEndpoint(config.url) ||
      requestWasAborted(config)
    ) {
      throw error
    }

    config.authRecoveryAttempted = true
    try {
      await refreshOnce()
    } catch {
      // The original protected request explains the session transition; a
      // refresh-endpoint error is an implementation detail and must not replace it.
      throw error
    }

    if (requestWasAborted(config)) throw error
    return instance.request(config)
  })
}
