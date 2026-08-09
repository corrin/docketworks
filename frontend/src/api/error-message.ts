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

/** Whether an unknown transport failure is an API response with this status. */
export function isApiErrorStatus(error: unknown, status: number): boolean {
  return isAxiosError(error) && error.response?.status === status
}
