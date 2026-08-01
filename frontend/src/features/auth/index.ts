/**
 * Auth feature: current-user query, login/logout mutations, and the login
 * error mapping ported from v1's stores/auth.ts. Cookies are HttpOnly and
 * server-set, so "logged in" is simply "GET /api/accounts/me/ succeeds".
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import {
  accountsLogoutCreateMutation,
  accountsMeRetrieveOptions,
  accountsMeRetrieveQueryKey,
  accountsTokenCreateMutation,
} from '@/api'

/** Query options for the authenticated user (GET /api/accounts/me/). */
export function meQueryOptions(): ReturnType<typeof accountsMeRetrieveOptions> {
  return {
    ...accountsMeRetrieveOptions(),
    // A 401 means "not logged in" — fail fast so route guards can redirect.
    retry: false,
    staleTime: 5 * 60_000,
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

/** POST /api/accounts/logout/ — server clears the JWT cookies. */
export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    ...accountsLogoutCreateMutation(),
    onSettled: () => {
      // All server state is user-scoped; drop it even if the backend call failed
      // (v1 cleared local auth state regardless).
      queryClient.clear()
    },
  })
}

interface LoginErrorResponseData {
  detail?: string
  non_field_errors?: string[]
}

/** Map a login failure to the user-facing message (ported from v1 authStore.login). */
export function loginErrorMessage(err: unknown): string {
  let errorMessage = 'An unexpected login error occurred.'

  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { status?: number; data?: LoginErrorResponseData } })
      .response
    const responseData = response?.data ?? {}
    const detailMessage = responseData.detail ?? responseData.non_field_errors?.[0]

    if (response?.status === 401 && detailMessage) {
      errorMessage = 'Wrong e-mail or password, please try again.'
    } else if (response?.status !== undefined && response.status >= 500) {
      errorMessage = 'Server error. Please try again later.'
    } else if (detailMessage) {
      errorMessage = detailMessage
    }
  } else if (typeof err === 'object' && err !== null && 'code' in err) {
    const code = (err as { code?: string }).code
    if (code === 'NETWORK_ERROR' || code === 'ERR_NETWORK') {
      errorMessage = 'Network error. Please check your internet connection.'
    }
  }

  return errorMessage
}
