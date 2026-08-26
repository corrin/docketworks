/**
 * Pure logic for the workshop "my time" calendar: deriving hours from a
 * start/end pair and shaping entries into FullCalendar events.
 *
 * `hours` is always derived from the time pair, never typed: the server
 * refuses a trio that disagrees, so the drawer offers no independent hours
 * field for the user to contradict.
 */

import type { WorkshopTimesheetEntryOut } from '@/api'

import { formatHoursDisplay } from './hours'

/** A timed entry carries a full pair; the guard narrows both nulls away. */
export interface TimedEntry extends WorkshopTimesheetEntryOut {
  start_time: string
  end_time: string
}

export interface DayEntriesSplit {
  timed: TimedEntry[]
  /** Rows the calendar cannot place (no or half a time pair) — rendered as a
      list below it so they stay visible and editable. */
  untimed: WorkshopTimesheetEntryOut[]
}

/** What the calendar draws; matches FullCalendar's EventInput shape. */
export interface MyTimeCalendarEvent {
  id: string
  title: string
  start: string
  end: string
}

const TIME_PATTERN = /^(\d{2}):(\d{2})/

function minutesOfDay(value: string): number | null {
  const match = TIME_PATTERN.exec(value)
  if (!match) return null
  return Number(match[1]) * 60 + Number(match[2])
}

/**
 * Decimal hours between two "HH:mm" input values, rounded to two decimals to
 * match the server's agreement tolerance; null when either is blank or the
 * end is not after the start.
 */
export function deriveHoursFromTimes(start: string, end: string): number | null {
  const startMinutes = minutesOfDay(start)
  const endMinutes = minutesOfDay(end)
  if (startMinutes === null || endMinutes === null) return null
  if (endMinutes <= startMinutes) return null
  return Math.round(((endMinutes - startMinutes) / 60) * 100) / 100
}

function isTimed(entry: WorkshopTimesheetEntryOut): entry is TimedEntry {
  return entry.start_time !== null && entry.end_time !== null
}

export function splitDayEntries(entries: WorkshopTimesheetEntryOut[]): DayEntriesSplit {
  return {
    timed: entries.filter(isTimed),
    untimed: entries.filter((entry) => !isTimed(entry)),
  }
}

export function eventTitle(entry: WorkshopTimesheetEntryOut): string {
  return `#${entry.job_number} ${entry.job_name} (${formatHoursDisplay(entry.hours)})`
}

/** Local (unzoned) datetimes, so the block sits where the wall clock says. */
export function calendarEvent(entry: TimedEntry): MyTimeCalendarEvent {
  return {
    id: entry.id,
    title: eventTitle(entry),
    start: `${entry.accounting_date}T${entry.start_time}`,
    end: `${entry.accounting_date}T${entry.end_time}`,
  }
}
