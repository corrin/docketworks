import dayjs from 'dayjs'
import { formatHoursDisplay } from '@/utils/string-formatting'

export function ensureTimeWithSeconds(time: string): string {
  if (!time) return '00:00:00'
  return time.length === 5 ? `${time}:00` : time
}

export function formatTimeInputValue(time?: string | null): string {
  if (!time) return ''
  return time.slice(0, 5)
}

export function minutesFromTime(time: string): number {
  if (!time) return 0
  const [hours, minutes] = ensureTimeWithSeconds(time)
    .split(':')
    .map((value) => Number(value) || 0)
  const result = hours * 60 + minutes
  return Math.min(Math.max(result, 0), 24 * 60 - 1)
}

export function minutesToTime(minutes: number): string {
  const clamped = Math.min(Math.max(minutes, 0), 24 * 60 - 1)
  const hours = Math.floor(clamped / 60)
  const mins = clamped % 60
  return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}`
}

export function normalizeTimeRange(startTime: string, endTime: string, slotMinutes: number) {
  const startMinutes = minutesFromTime(startTime || '00:00')
  let endMinutes = minutesFromTime(endTime || '00:00')
  if (endMinutes <= startMinutes) {
    endMinutes = Math.min(startMinutes + slotMinutes, 24 * 60 - 1)
  }
  return {
    start: minutesToTime(startMinutes),
    end: minutesToTime(endMinutes),
  }
}

export function combineDateTime(dateKey: string, time: string): Date {
  return new Date(`${dateKey}T${ensureTimeWithSeconds(time)}`)
}

export function calculateDurationHours(startTime: string, endTime: string): number {
  if (!startTime || !endTime) return 0
  const start = dayjs(`1970-01-01T${ensureTimeWithSeconds(startTime)}`)
  const end = dayjs(`1970-01-01T${ensureTimeWithSeconds(endTime)}`)
  const minutes = end.diff(start, 'minute', true)
  if (Number.isNaN(minutes) || minutes <= 0) return 0
  return Math.round((minutes / 60) * 100) / 100
}

export function formatHoursValue(hours: number): string {
  return formatHoursDisplay(hours)
}
