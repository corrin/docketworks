/**
 * Local-date arithmetic on YYYY-MM-DD strings.
 *
 * Every function round-trips through new Date(y, m-1, d) — local midnight —
 * never new Date('YYYY-MM-DD') or toISOString(), both of which go through UTC
 * and can shift the date by a day in NZ. (localIsoDate in format.ts carries
 * the same constraint.)
 */

function parseLocal(isoDate: string): Date {
  const [year, month, day] = isoDate.split('-').map((part) => Number.parseInt(part, 10))
  if (year === undefined || month === undefined || day === undefined) {
    throw new Error(`Not a YYYY-MM-DD date: ${isoDate}`)
  }
  return new Date(year, month - 1, day)
}

function toIso(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/** Shift a local date by whole days. */
export function shiftDate(isoDate: string, days: number): string {
  const date = parseLocal(isoDate)
  date.setDate(date.getDate() + days)
  return toIso(date)
}

function isWeekend(date: Date): boolean {
  const day = date.getDay()
  return day === 0 || day === 6
}

/**
 * Step to the adjacent day, skipping Saturday/Sunday unless weekend
 * timesheets are enabled (companyDefaults.weekend_timesheets_enabled).
 */
export function nextWeekday(isoDate: string, direction: 1 | -1, weekendEnabled: boolean): string {
  const date = parseLocal(isoDate)
  date.setDate(date.getDate() + direction)
  if (weekendEnabled) return toIso(date)
  while (isWeekend(date)) {
    date.setDate(date.getDate() + direction)
  }
  return toIso(date)
}

/**
 * The date itself, pushed forward to Monday when it falls on a disabled
 * weekend (the Today button's landing rule).
 */
export function weekdayAdjusted(isoDate: string, weekendEnabled: boolean): string {
  if (weekendEnabled) return isoDate
  const date = parseLocal(isoDate)
  while (isWeekend(date)) {
    date.setDate(date.getDate() + 1)
  }
  return toIso(date)
}
