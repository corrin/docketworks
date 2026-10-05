/**
 * Pure logic for the workshop "my time" calendar: deriving hours from a
 * start/end pair and shaping entries into FullCalendar events.
 *
 * `hours` is always derived from the time pair, never typed: the server
 * refuses a trio that disagrees, so the drawer offers no independent hours
 * field for the user to contradict.
 */

import type {
  CompanyDefaultsOut,
  TimesheetJobOut,
  WorkshopTimesheetEntryOut,
  WorkshopTimesheetEntryUpdateRequest,
} from '@/api'

import { formatHoursDisplay } from '@/lib/format'

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
  /** Where the entry stands, as words to print on the block. */
  marks: string[]
}

/**
 * Where an entry stands, as the words the worker reads on it. Each mark is a
 * boolean the server computed; this is the one place they become labels, so
 * the calendar block, the untimed list and the drawer cannot disagree.
 */
export function entryMarks(entry: WorkshopTimesheetEntryOut): string[] {
  const marks = [entry.approved ? 'Approved' : 'Waiting']
  if (entry.entered_late) marks.push('Entered late')
  if (entry.remote_entry) marks.push('Suspicious remote entry')
  return marks
}

/**
 * Whether this person may no longer change the entry. Approved time is what
 * payroll pays, so only the office changes it; the server refuses the write
 * either way, and this keeps the drawer from offering one it will refuse.
 */
export function entryLockedFor(
  entry: WorkshopTimesheetEntryOut,
  user: { is_office_staff: boolean },
): boolean {
  return entry.approved && !user.is_office_staff
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

/**
 * The PATCH field a job repick contributes. Billability on a move is the
 * server's rule (move_time_line): sending is_billable from here discarded an
 * explicit unbillable choice on a normal-to-normal move.
 */
export function jobChangeFields(
  entry: WorkshopTimesheetEntryOut,
  jobId: string,
): { job_id?: string } {
  if (jobId === entry.job_id) return {}
  return { job_id: jobId }
}

/** The pay rates a workshop entry can be booked at; `Ord` is ordinary time. */
export const RATE_OPTIONS = [
  { label: 'Ord', multiplier: 1 },
  { label: '1.5', multiplier: 1.5 },
  { label: '2.0', multiplier: 2 },
] as const

type RateOption = { label: string; multiplier: number }

/**
 * The rates the select offers for an entry: the three standard ones, plus the
 * entry's stored rate when it is none of them (set from the office grid), so
 * the stored rate stays selectable for as long as the drawer is open.
 */
export function rateOptionsFor(storedMultiplier: number | null): readonly RateOption[] {
  if (
    storedMultiplier === null ||
    RATE_OPTIONS.some((option) => option.multiplier === storedMultiplier)
  ) {
    return RATE_OPTIONS
  }
  return [...RATE_OPTIONS, { label: rateLabel(storedMultiplier), multiplier: storedMultiplier }]
}

/**
 * The job the drawer is booking against. The job the picker handed over is
 * used as it is: a job found through the picker's whole-table search is not
 * in the loaded list, and looking it up there would lose it.
 */
export function resolveSelectedJob<T extends { id: string }>(
  picked: T | null,
  listed: readonly T[],
  jobId: string | null,
): T | null {
  if (picked !== null && picked.id === jobId) return picked
  return listed.find((job) => job.id === jobId) ?? null
}

/** What the drawer's rate select and billable tick hold. */
export interface EntryBillingValues {
  /** The tick as the user set it; null while they have not touched it. */
  billableChoice: boolean | null
  rateMultiplier: number
}

/**
 * The PATCH fields the rate select and billable tick contribute. The server
 * reads the presence of `is_billable` as an explicit choice (move_time_line):
 * it is sent whenever the user set the tick, even to the stored value, so a
 * choice survives a job move — and never otherwise, so a move off a shop job
 * with the tick untouched is still the server's to re-bill.
 */
export function billingChangeFields(
  entry: WorkshopTimesheetEntryOut,
  form: EntryBillingValues,
): { is_billable?: boolean; wage_rate_multiplier?: number } {
  return {
    ...(form.billableChoice === null ? {} : { is_billable: form.billableChoice }),
    ...(form.rateMultiplier === entry.wage_rate_multiplier
      ? {}
      : { wage_rate_multiplier: form.rateMultiplier }),
  }
}

type BillingJob = Pick<TimesheetJobOut, 'id' | 'shop_job' | 'status'>

/** Whether time on the job can be invoiced: shop work and special jobs cannot
    (the server's rule, job_service._bills_its_time). */
export function billsItsTime(job: BillingJob): boolean {
  return !job.shop_job && job.status !== 'special'
}

/**
 * What the billable tick shows, which is what the save will produce. A job
 * that cannot bill shows unticked whatever was chosen. Untouched, a new entry
 * is billable, and an entry moved off a job that could not bill becomes
 * billable — the server's rule, mirrored here so the tick does not show one
 * thing and the save do another.
 */
export function shownBillable(form: {
  entry: WorkshopTimesheetEntryOut | null
  /** The entry's current job, when the job list still offers it. */
  sourceJob: BillingJob | null
  selectedJob: BillingJob | null
  billableChoice: boolean | null
}): boolean {
  const { entry, sourceJob, selectedJob, billableChoice } = form
  if (selectedJob !== null && !billsItsTime(selectedJob)) return false
  if (billableChoice !== null) return billableChoice
  if (entry === null) return true
  const movedOffUnbillableJob =
    sourceJob !== null &&
    !billsItsTime(sourceJob) &&
    selectedJob !== null &&
    selectedJob.id !== entry.job_id
  return movedOffUnbillableJob ? true : entry.is_billable
}

const WEEKDAY_START_KEYS = [
  'mon_start',
  'tue_start',
  'wed_start',
  'thu_start',
  'fri_start',
] as const

/** The company configures no weekend hours; a weekend entry opens here. */
const WEEKEND_DAY_START = '08:00'

/** When the working day starts on `isoDate`, as an "HH:mm" time-input value. */
export function workingDayStart(
  isoDate: string,
  defaults: Pick<CompanyDefaultsOut, (typeof WEEKDAY_START_KEYS)[number]>,
): string {
  const weekday = new Date(`${isoDate}T00:00:00`).getDay()
  const key = WEEKDAY_START_KEYS[weekday - 1]
  return key === undefined ? WEEKEND_DAY_START : defaults[key].slice(0, 5)
}

/** How many different jobs the day's entries are booked to. */
export function distinctJobCount(entries: WorkshopTimesheetEntryOut[]): number {
  return new Set(entries.map((entry) => entry.job_id)).size
}

/** A rate multiplier as the workshop reads it: "Ord", "1.5x", "2x". */
export function rateLabel(multiplier: number): string {
  return multiplier === 1 ? 'Ord' : `${multiplier}x`
}

/** A start/end pair of "HH:mm" time-input values. */
export interface TimeRange {
  start: string
  end: string
}

/** The length a new entry opens at, and the calendar's slot size. */
const DEFAULT_SLOT_MINUTES = 30
/** A day's entry cannot run past its own date. */
const LAST_MINUTE_OF_DAY = 24 * 60 - 1

function timeOfDay(minutes: number): string {
  const clamped = Math.min(Math.max(minutes, 0), LAST_MINUTE_OF_DAY)
  const hours = Math.floor(clamped / 60)
  return `${String(hours).padStart(2, '0')}:${String(clamped % 60).padStart(2, '0')}`
}

function requireMinutes(value: string): number {
  const minutes = minutesOfDay(value)
  if (minutes === null) throw new Error(`Not a time of day: "${value}"`)
  return minutes
}

/**
 * A range that is always at least a minute long and inside the day. An end
 * past midnight stops at 23:59; when that leaves nothing after the start (a
 * 23:59 start), the start is pulled back a minute instead — a zero-length
 * entry cannot be saved, and no chip could then mend it.
 */
function bookableRange(startMinutes: number, endMinutes: number): TimeRange {
  const end = Math.min(endMinutes, LAST_MINUTE_OF_DAY)
  const start = Math.min(startMinutes, end - 1)
  return { start: timeOfDay(start), end: timeOfDay(end) }
}

/** One default slot starting at `start`. */
export function slotFrom(start: string): TimeRange {
  const startMinutes = requireMinutes(start)
  return bookableRange(startMinutes, startMinutes + DEFAULT_SLOT_MINUTES)
}

/**
 * Where a new entry opens: at the tapped slot, else straight after the day's
 * latest finish (the next job usually starts when the last one stopped), else
 * at the start of the working day.
 */
export function defaultNewEntryRange(
  entries: WorkshopTimesheetEntryOut[],
  dayStart: string,
  tappedStart: string | null,
): TimeRange {
  if (tappedStart !== null) return slotFrom(tappedStart)
  const finishes = splitDayEntries(entries).timed.map((entry) => requireMinutes(entry.end_time))
  if (finishes.length === 0) return slotFrom(dayStart)
  return slotFrom(timeOfDay(Math.max(...finishes)))
}

/** The job of the entry booked most recently, which a new entry defaults to. */
export function lastUsedJobId(entries: WorkshopTimesheetEntryOut[]): string | null {
  let latest: WorkshopTimesheetEntryOut | null = null
  for (const entry of entries) {
    if (latest === null || entry.created_at > latest.created_at) latest = entry
  }
  return latest === null ? null : latest.job_id
}

/** "Now": one default slot starting at the wall-clock minute. */
export function slotFromNow(now: Date): TimeRange {
  return slotFrom(timeOfDay(now.getHours() * 60 + now.getMinutes()))
}

/**
 * Move the end by `deltaMinutes`, keeping the start. The end never crosses the
 * start: pulling it back that far leaves a one-minute entry, the shortest the
 * server accepts.
 */
export function adjustEnd(range: TimeRange, deltaMinutes: number): TimeRange {
  const start = requireMinutes(range.start)
  const moved = requireMinutes(range.end) + deltaMinutes
  return bookableRange(start, moved > start ? moved : start + 1)
}

/**
 * "Fill gap": run the entry up to the day's next start, or to the end of the
 * day when nothing follows it.
 */
export function fillGapToNextEntry(start: string, entries: WorkshopTimesheetEntryOut[]): TimeRange {
  const from = requireMinutes(start)
  const laterStarts = splitDayEntries(entries)
    .timed.map((entry) => requireMinutes(entry.start_time))
    .filter((minutes) => minutes > from)
  return bookableRange(
    from,
    laterStarts.length === 0 ? LAST_MINUTE_OF_DAY : Math.min(...laterStarts),
  )
}

/** What the drawer's form holds when the user submits an edit. */
export interface EntryFormValues {
  jobId: string
  start: string
  end: string
  /** Derived from the pair; null means both time inputs are blank. */
  hours: number | null
  description: string
}

/**
 * The PATCH body for an edited entry. With no derived hours the times and
 * hours are left untouched — that is the untimed-entry edit (description or
 * job only), where imposing a pair would also silently replace the stored
 * hours.
 */
export function entryUpdateBody(
  entry: WorkshopTimesheetEntryOut,
  form: EntryFormValues,
): WorkshopTimesheetEntryUpdateRequest {
  const trimmed = form.description.trim()
  return {
    entry_id: entry.id,
    ...jobChangeFields(entry, form.jobId),
    ...(form.hours === null
      ? {}
      : {
          hours: form.hours,
          start_time: `${form.start}:00`,
          end_time: `${form.end}:00`,
        }),
    description: trimmed === '' ? null : trimmed,
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
    marks: entryMarks(entry),
  }
}
