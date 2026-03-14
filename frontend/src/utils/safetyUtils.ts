import { debugLog } from '@/utils/debug'
export function createSafeDate(dateValue: string | undefined): Date {
  if (!dateValue) {
    return new Date()
  }

  try {
    const date = new Date(dateValue)

    if (isNaN(date.getTime())) {
      debugLog('Invalid date value:', dateValue)
      return new Date()
    }
    return date
  } catch (error) {
    debugLog('Error creating date:', error)
    return new Date()
  }
}

export function getSafeNumber(value: number | undefined, defaultValue: number = 0): number {
  if (value === undefined || value === null || isNaN(value)) {
    return defaultValue
  }

  return value
}

export function getSafeString(value: string | undefined, defaultValue: string = ''): string {
  if (!value) {
    return defaultValue
  }

  return value
}
