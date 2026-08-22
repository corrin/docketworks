import { isAxiosError } from 'axios'

function isRecord(value: unknown): value is Record<PropertyKey, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * The user-facing message for a failed API call. Prefers the backend's own
 * `message`/`detail`/`error` (errors are transparent — ADR 0038) over axios's
 * generic "Request failed with status code N". `error` is the key the Xero
 * document endpoints use (XeroDocumentErrorResponse), carrying calc and
 * configuration guidance the user must see.
 */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error) && isRecord(error.response?.data)) {
    const data = error.response.data
    if (typeof data.message === 'string' && data.message !== '') {
      return data.message
    }
    if (typeof data.detail === 'string' && data.detail !== '') {
      return data.detail
    }
    if (typeof data.error === 'string' && data.error !== '') {
      return data.error
    }
  }
  if (error instanceof Error && error.message !== '') {
    return error.message
  }
  return fallback
}

/** Persisted backend error id, when this was a genuine application fault. */
export function apiErrorId(error: unknown): string | null {
  if (!isAxiosError(error) || !isRecord(error.response?.data)) return null
  const errorId = error.response.data.error_id
  return typeof errorId === 'string' && errorId !== '' ? errorId : null
}

/** Whether an unknown transport failure is an API response with this status. */
export function isApiErrorStatus(error: unknown, status: number): boolean {
  return isAxiosError(error) && error.response?.status === status
}

/** The response body of a failed call, for endpoints whose error status
    carries a typed payload (e.g. the 409 PhoneOwnership conflict). Callers
    validate the shape themselves — this only crosses the axios boundary. */
export function apiErrorBody(error: unknown): unknown {
  return isAxiosError(error) ? error.response?.data : undefined
}

/** Authentication challenge emitted by the app session boundary, not a domain 401. */
export function isSessionAuthenticationError(error: unknown): boolean {
  if (!isAxiosError(error) || error.response?.status !== 401 || !isRecord(error.response.data)) {
    return false
  }
  return error.response.data.code === 'authentication_required'
}

/** A transport outage worth a brief retry and a recoverable connection screen. */
export function isAvailabilityError(error: unknown): boolean {
  if (!isAxiosError(error) || error.code === 'ERR_CANCELED') return false
  if (error.response === undefined) return true
  return [502, 503, 504].includes(error.response.status)
}
