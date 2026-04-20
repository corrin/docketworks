import type { DateValue } from '@internationalized/date'
import { CalendarDate } from '@internationalized/date'
import { debugLog } from '@/utils/debug'

/**
 * Formats a Date object as YYYY-MM-DD string in local timezone.
 * Use this instead of date.toISOString().split('T')[0] which uses UTC
 * and can return yesterday's date in NZ timezone.
 *
 * @param date - Date to format (defaults to now)
 * @returns Date string in YYYY-MM-DD format
 */
export function toLocalDateString(date: Date = new Date()): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/**
 * Returns today's date as YYYY-MM-DD in the local timezone, shifting back to
 * Friday when today is a Saturday or Sunday.
 */
export function getLatestWeekdayDate(date: Date = new Date()): string {
  const shifted = new Date(date)
  const day = shifted.getDay()
  if (day === 6) shifted.setDate(shifted.getDate() - 1)
  if (day === 0) shifted.setDate(shifted.getDate() - 2)
  return toLocalDateString(shifted)
}

export function toDateValue(date: Date | string | null | undefined): DateValue | undefined {
  if (!date) {
    return undefined
  }

  const dateObj = typeof date === 'string' ? new Date(date) : date

  if (isNaN(dateObj.getTime())) {
    return undefined
  }
  try {
    const year = dateObj.getFullYear()
    const month = dateObj.getMonth() + 1
    const day = dateObj.getDate()

    return new CalendarDate(year, month, day)
  } catch (error) {
    debugLog('Failed to convert date to DateValue:', error)
    return undefined
  }
}

export function fromDateValue(dateValue: DateValue | null | undefined): Date | null {
  if (!dateValue) {
    return null
  }

  try {
    return new Date(dateValue.year, dateValue.month - 1, dateValue.day)
  } catch (error) {
    debugLog('Failed to convert DateValue to Date:', error)
    return null
  }
}
