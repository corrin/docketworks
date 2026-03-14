export function extractErrorMessage(error: unknown, fallbackMessage = 'An error occurred'): string {
  if (!error) {
    return fallbackMessage
  }

  if (typeof error === 'object' && error !== null && 'response' in error) {
    const apiError = error as { response?: { data?: unknown } }
    const responseData = apiError.response?.data

    if (responseData && typeof responseData === 'object') {
      const data = responseData as Record<string, unknown>
      // Prefer details over generic error messages
      const details = data.details as string | undefined
      const error = data.error as string | undefined
      const message = data.message as string | undefined

      // If we have both error and details, combine them for context
      if (error && details) {
        return `${error}: ${details}`
      }
      // Otherwise return the first available message
      const text = details || error || message
      if (typeof text === 'string') return text
    }
  }

  if (error instanceof Error) {
    return error.message
  }

  if (typeof error === 'object' && 'message' in error) {
    const messageError = error as { message: unknown }
    if (typeof messageError.message === 'string') {
      return messageError.message
    }
  }

  if (typeof error === 'string') {
    return error
  }

  return fallbackMessage
}

export function createErrorToast() {
  return {
    duration: 0,
    action: {
      label: 'Dismiss',
      onClick: () => {},
    },
  }
}

export function isAuthenticationError(error: unknown): boolean {
  const possibleErrorObject = typeof error === 'object' && error !== null ? error : null
  const responseStatus =
    possibleErrorObject && 'response' in possibleErrorObject
      ? (possibleErrorObject as { response?: { status?: number } }).response?.status
      : undefined
  const messageValue =
    typeof error === 'string'
      ? error
      : possibleErrorObject && 'message' in possibleErrorObject
        ? (possibleErrorObject as { message?: unknown }).message
        : undefined
  const messageText = typeof messageValue === 'string' ? messageValue : undefined

  return responseStatus === 401 || messageText?.includes('auth') || false
}
