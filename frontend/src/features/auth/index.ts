/**
 * Auth feature: current-user query, login/logout mutations, and the login
 * error mapping. Cookies are HttpOnly and
 * server-set, so "logged in" is simply "GET /api/accounts/me/ succeeds".
 */
import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'

import {
  accountsLogoutCreateMutation,
  accountsMePasswordCreateMutation,
  accountsMeRetrieveOptions,
  accountsMeRetrieveQueryKey,
  accountsTokenCreateMutation,
  isApiErrorStatus,
  isAvailabilityError,
  type UserProfile,
} from '@/api'

export interface LoginSearch {
  redirect?: string
}

export type SessionResolution =
  | { state: 'authenticated'; user: UserProfile }
  | { state: 'unauthenticated' }
  | { state: 'unavailable'; error: unknown }

/** Only same-origin absolute paths may become post-auth destinations. */
export function safeInternalRedirect(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) {
    return undefined
  }
  // Validate the CANONICALIZED value, not the raw string: browsers treat
  // backslashes as slashes during URL parsing, so '/\attacker.example'
  // becomes the protocol-relative '//attacker.example' when navigated.
  const base = 'http://internal.invalid'
  const parsed = new URL(value, base)
  if (parsed.origin !== base) {
    return undefined
  }
  return parsed.pathname + parsed.search + parsed.hash
}

export function retryUnavailableSession(failureCount: number, error: unknown): boolean {
  return failureCount < 2 && isAvailabilityError(error)
}

/** Query options for the authenticated user (GET /api/accounts/me/). */
export function meQueryOptions(): ReturnType<typeof accountsMeRetrieveOptions> {
  return {
    ...accountsMeRetrieveOptions(),
    // Authentication is conclusive after the transport has attempted refresh;
    // only brief availability failures merit another probe.
    retry: retryUnavailableSession,
    retryDelay: (attemptIndex) => 250 * 2 ** attemptIndex,
    staleTime: 5 * 60_000,
  }
}

/** Resolve the session without collapsing an outage into "logged out". */
export async function resolveSession(queryClient: QueryClient): Promise<SessionResolution> {
  try {
    const user = await queryClient.ensureQueryData(meQueryOptions())
    return { state: 'authenticated', user }
  } catch (error) {
    if (isApiErrorStatus(error, 401)) return { state: 'unauthenticated' }
    return { state: 'unavailable', error }
  }
}

/** POST /api/accounts/token/ — server sets HttpOnly JWT cookies on success. */
export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    ...accountsTokenCreateMutation(),
    onSuccess: () => {
      // Drop any cached pre-login /me result so guards refetch with the new session.
      queryClient.removeQueries({ queryKey: accountsMeRetrieveQueryKey() })
    },
  })
}

/** POST /api/accounts/me/password/ — the self-service credential write. */
export function useChangePassword() {
  const queryClient = useQueryClient()
  return useMutation({
    ...accountsMePasswordCreateMutation(),
    onSuccess: () => {
      // A successful change clears password_needs_reset server-side; drop the
      // cached /me so route guards refetch the cleared flag (same pattern as
      // useLogin — the cached profile is authoritative for navigation).
      queryClient.removeQueries({ queryKey: accountsMeRetrieveQueryKey() })
    },
  })
}

/** POST /api/accounts/logout/ — server clears the JWT cookies. */
export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    ...accountsLogoutCreateMutation(),
    onSettled: () => {
      // All server state is user-scoped; drop it even if the backend call failed
      // Backend logout failure must not retain another user's cached data.
      queryClient.clear()
    },
  })
}

interface LoginErrorResponseData {
  detail?: string
  non_field_errors?: string[]
}

function isRecord(value: unknown): value is Record<PropertyKey, unknown> {
  return typeof value === 'object' && value !== null
}

/** Map a login failure to the user-facing message. */
export function loginErrorMessage(err: unknown): string {
  let errorMessage = 'An unexpected login error occurred.'

  if (isRecord(err)) {
    const response = isRecord(err.response) ? err.response : undefined
    const responseData: LoginErrorResponseData = isRecord(response?.data)
      ? {
          detail: typeof response.data.detail === 'string' ? response.data.detail : undefined,
          non_field_errors: Array.isArray(response.data.non_field_errors)
            ? response.data.non_field_errors.filter(
                (message): message is string => typeof message === 'string',
              )
            : undefined,
        }
      : {}
    const detailMessage = responseData.detail ?? responseData.non_field_errors?.[0]
    const status = typeof response?.status === 'number' ? response.status : undefined

    if (status === 401 && detailMessage) {
      errorMessage = 'Wrong e-mail or password, please try again.'
    } else if (status !== undefined && status >= 500) {
      errorMessage = 'Server error. Please try again later.'
    } else if (detailMessage) {
      errorMessage = detailMessage
    } else if (err.code === 'NETWORK_ERROR' || err.code === 'ERR_NETWORK') {
      errorMessage = 'Network error. Please check your internet connection.'
    }
  }

  return errorMessage
}
