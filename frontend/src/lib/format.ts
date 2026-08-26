const NZD = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/**
 * The one currency formatter. E2E specs assert its exact output across pages
 * (a table cell must string-equal the detail view), so every money display
 * goes through here — a second formatter would diverge invisibly.
 */
export function formatCurrency(value: number): string {
  return NZD.format(value)
}

/**
 * toFixed(1), not Intl percent formatting: rates travel as percentage
 * points (0-100, ADR 0046), and Intl's percent style would multiply by
 * 100 again.
 */
export function formatPercentage(value: number): string {
  return `${value.toFixed(1)}%`
}

const NZ_DATE = new Intl.DateTimeFormat('en-NZ', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  // UTC, matching how date-only ISO strings parse: new Date('2026-08-09') is
  // UTC midnight, and formatting it in a west-of-UTC zone shifts it a day.
  timeZone: 'UTC',
})

/**
 * A playback clock: `m:ss`, minutes unbounded (`10:16`, `0:07`, `72:00`).
 * Whole seconds, floored — a player's position ticks down to the second and
 * rounding up would read a second ahead of the audio.
 */
export function formatClock(seconds: number): string {
  const whole = Math.floor(seconds)
  const minutes = Math.floor(whole / 60)
  const remainder = whole % 60
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

/** The one date formatter, for the same cross-page string-equality reason. */
export function formatDate(isoDate: string): string {
  return NZ_DATE.format(new Date(isoDate))
}

const NZ_DATE_LONG = new Intl.DateTimeFormat('en-NZ', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  // Same date-only rule as NZ_DATE: the input parses as UTC midnight.
  timeZone: 'UTC',
})

/** The one long-form date formatter (weekday plus full month) — page-header
    dates go through here, for the same cross-page string-equality reason as
    formatDate. */
export function formatDateLong(isoDate: string): string {
  return NZ_DATE_LONG.format(new Date(isoDate))
}

/** Today as YYYY-MM-DD in the browser's timezone (UTC slicing shifts NZ dates). */
export function localIsoDate(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

const NZ_DATE_TIME = new Intl.DateTimeFormat('en-NZ', {
  dateStyle: 'short',
  timeStyle: 'short',
  // No timeZone: unlike formatDate above, these values carry a time of day
  // and an offset. Pinning UTC would show a 9am Auckland call as 9pm the day
  // before, so the reader's own zone is the only correct one here.
})

/** The one timestamp formatter, for the same cross-page string-equality
    reason as formatDate — dates with a time of day go through here. */
export function formatDateTime(iso: string): string {
  return NZ_DATE_TIME.format(new Date(iso))
}

/**
 * A wire event type as a heading: `costline_updated` reads "Costline
 * Updated". Fable: the alternative was a hand-written label table, rejected
 * because the backend adds event types without asking the frontend and an
 * unlisted one would then render blank rather than merely unpolished
 * (`entry_type` and `costline_kind` are closed sets and `history.ts` throws
 * on an undeclared one).
 */
export function formatEventType(snakeCase: string): string {
  return snakeCase
    .split('_')
    .map((word) => (word === '' ? word : word[0]!.toUpperCase() + word.slice(1)))
    .join(' ')
}
