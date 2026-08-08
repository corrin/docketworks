import { isAxiosError } from 'axios'

function isRecord(value: unknown): value is Record<PropertyKey, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * The user-facing message for a failed API call. Prefers the backend's own
 * `message`/`detail` (errors are transparent — ADR 0038) over axios's generic
 * "Request failed with status code N".
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
