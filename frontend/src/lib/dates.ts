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
  // NaN, not undefined, is what parseInt yields for garbage — and the date
  // arrives from a user-editable URL search param.
  if (
    year === undefined ||
    month === undefined ||
    day === undefined ||
    Number.isNaN(year) ||
    Number.isNaN(month) ||
    Number.isNaN(day)
  ) {
    throw new Error(`Not a YYYY-MM-DD date: ${isoDate}`)
  }
  return new Date(year, month - 1, day)
}

function toIso(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/**
 * Whether a string is a real YYYY-MM-DD calendar date. The route search
 * validators use this so a hand-edited URL falls back to today instead of
 * reaching the date helpers (which throw on garbage).
 */
export function isIsoDateString(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [yearPart, monthPart, dayPart] = value.split('-')
  const year = Number(yearPart)
  const month = Number(monthPart)
  const day = Number(dayPart)
  const date = new Date(year, month - 1, day)
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day
}

/**
 * Whether a string is a real YYYY-MM month within the range the reports API
 * accepts. The year bound mirrors the server's own (apps/accounting/api.py),
 * so a hand-edited URL falls back to the current month rather than
 * round-tripping to a 422 the page would have to render as an error.
 */
export function isIsoMonthString(value: string): boolean {
  if (!/^\d{4}-\d{2}$/.test(value)) return false
  const [yearPart, monthPart] = value.split('-')
  const year = Number(yearPart)
  const month = Number(monthPart)
  return year >= 2000 && year <= 2100 && month >= 1 && month <= 12
}

/** Shift a YYYY-MM month by whole months, rolling the year over. */
export function shiftMonth(isoMonth: string, months: number): string {
  const [yearPart, monthPart] = isoMonth.split('-')
  const year = Number(yearPart)
  const month = Number(monthPart)
  if (Number.isNaN(year) || Number.isNaN(month)) {
    throw new Error(`Not a YYYY-MM month: ${isoMonth}`)
  }
  // Date normalises out-of-range months into the neighbouring year, which is
  // the whole reason this goes through Date rather than modular arithmetic.
  const shifted = new Date(year, month - 1 + months, 1)
  return `${shifted.getFullYear()}-${String(shifted.getMonth() + 1).padStart(2, '0')}`
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

/**
 * The Monday of the week containing the given date.
 *
 * Opus: Payroll weeks are Monday-anchored, so every week-based screen needs this.
 * It lives here rather than privately in a page so there is one answer to
 * "which week is this date in" (ADR 0039).
 */
export function mondayOf(isoDate: string): string {
  const date = parseLocal(isoDate)
  const day = date.getDay()
  // Opus: getDay() is 0 for Sunday, which belongs to the week that started six days
  // earlier, not the one starting tomorrow.
  date.setDate(date.getDate() - day + (day === 0 ? -6 : 1))
  return toIso(date)
}

/** The (start, end) of the `days`-long span beginning at a date, inclusive. */
export function spanFrom(isoDate: string, days: number): { startDate: string; endDate: string } {
  return { startDate: isoDate, endDate: shiftDate(isoDate, days - 1) }
}
