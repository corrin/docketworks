import { AxiosError } from 'axios'
import { debugLog } from '@/utils/debug'

export function extractErrorMessage(error: unknown): string {
  debugLog('Extracting error message from:', error)

  if (error && typeof error === 'object' && 'isAxiosError' in error) {
    const axiosError = error as AxiosError

    if (axiosError.code === 'ECONNABORTED' && axiosError.message?.includes('timeout')) {
      return 'Operation is taking longer than expected - please wait a moment and check if it completed successfully'
    }

    if (axiosError.response?.data) {
      const data = axiosError.response.data as Record<string, unknown>

      if (typeof data === 'string') {
        return data
      }

      if (data.error) {
        return String(data.error)
      }

      if (data.message) {
        return String(data.message)
      }

      if (data.detail) {
        return String(data.detail)
      }

      if (data.errors) {
        if (Array.isArray(data.errors)) {
          return data.errors.join(', ')
        }
        if (typeof data.errors === 'object' && data.errors !== null) {
          const errorMessages = Object.values(data.errors).flat()
          return errorMessages.join(', ')
        }
      }

      if (typeof data === 'object' && data !== null) {
        const values = Object.values(data)
        for (const value of values) {
          if (typeof value === 'string' && value.length > 0) {
            return value
          }
        }
      }
    }

    if (axiosError.response?.statusText) {
      return `${axiosError.response.status}: ${axiosError.response.statusText}`
    }

    switch (axiosError.response?.status) {
      case 400:
        return 'Invalid request - please check the data sent'
      case 401:
        return 'Unauthorised - please log in again'
      case 403:
        return 'Access denied - you do not have permission for this operation'
      case 404:
        return 'Resource not found'
      case 422:
        return 'Invalid data provided'
      case 500:
        return 'Internal server error - please try again later'
      case 502:
        return 'Server temporarily unavailable'
      case 503:
        return 'Service temporarily unavailable'
      default:
        return `HTTP error ${axiosError.response?.status ?? 'unknown'}`
    }
  }

  if (error instanceof Error) {
    return error.message
  }

  if (typeof error === 'string') {
    return error
  }

  return 'Unknown error in operation'
}

export function extractQuoteErrorMessage(error: unknown): string {
  const baseMessage = extractErrorMessage(error)

  if (error && typeof error === 'object' && 'isAxiosError' in error) {
    const axiosError = error as AxiosError
    if (axiosError.code === 'ECONNABORTED' && axiosError.message?.includes('timeout')) {
      return 'Quote creation is taking longer than expected. The spreadsheet may have been created successfully - please refresh the page to check.'
    }
  }

  if (baseMessage.includes('No master quote template URL')) {
    return 'Quote template not configured - please configure the master template in company settings'
  }

  if (baseMessage.includes('Sheet not found')) {
    return 'Spreadsheet not found - please check if the spreadsheet still exists in Google Drive'
  }

  if (baseMessage.includes('Permission denied')) {
    return 'Permission denied - please check if the application has access to the spreadsheet'
  }

  if (baseMessage.includes('Invalid sheet format')) {
    return 'Invalid spreadsheet format - please use the official template for quotes'
  }

  return baseMessage
}

export function logError(
  context: string,
  error: unknown,
  additionalData?: Record<string, unknown>,
): void {
  console.group(`Error in ${context}`)
  debugLog('Original error:', error)
  debugLog('Extracted message:', extractErrorMessage(error))
  if (additionalData) {
    debugLog('Additional data:', additionalData)
  }
  console.groupEnd()
}
