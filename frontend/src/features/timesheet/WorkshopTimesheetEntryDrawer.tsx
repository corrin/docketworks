import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { timesheetsJobsRetrieveOptions } from '@/api'
import type {
  TimesheetJobOut,
  WorkshopTimesheetEntryOut,
  WorkshopTimesheetEntryRequest,
  WorkshopTimesheetEntryUpdateRequest,
} from '@/api'
import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer'
import { INPUT_CLASS } from '@/components/ui/field'
import { TOUCH_TARGET_CLASS } from '@/components/ui/touch'
import { JobPicker } from '@/features/shared/JobPicker'

import { formatDateLong, formatHoursDisplay } from '@/lib/format'
import {
  adjustEnd,
  billingChangeFields,
  billsItsTime,
  defaultNewEntryRange,
  deriveHoursFromTimes,
  entryUpdateBody,
  fillGapToNextEntry,
  lastUsedJobId,
  RATE_OPTIONS,
  rateLabel,
  shownBillable,
  slotFrom,
  slotFromNow,
  type TimeRange,
} from './myTime'
import { timesheetJobSearchOptions } from './timesheetJobSearch'

export type EntryDrawerState =
  | { mode: 'closed' }
  | { mode: 'create'; start: string | null }
  | { mode: 'edit'; entry: WorkshopTimesheetEntryOut }

interface WorkshopTimesheetEntryDrawerProps {
  state: EntryDrawerState
  /** The day new entries book to, YYYY-MM-DD. */
  date: string
  /** Every entry already on that day: a new entry defaults its job and start
      from them, and "Fill gap" runs up to the next one. */
  dayEntries: WorkshopTimesheetEntryOut[]
  /** When the working day starts on that date, "HH:mm". */
  dayStart: string
  saving: boolean
  onCreate: (body: WorkshopTimesheetEntryRequest) => Promise<boolean>
  onUpdate: (body: WorkshopTimesheetEntryUpdateRequest) => Promise<boolean>
  onDelete: (entryId: string) => Promise<boolean>
  onClose: () => void
}

/** "HH:MM:SS" from the wire → the "HH:mm" a time input holds. */
function inputTime(value: string | null): string {
  return value === null ? '' : value.slice(0, 5)
}

/**
 * Add/edit drawer for one workshop entry: job, start/end time, rate,
 * billable, description.
 *
 * Fable: Hours are always derived from the time pair (the server refuses a
 * trio that disagrees), so the drawer shows the duration instead of asking
 * for it. Workshop staff choose the rate and whether the time is billable;
 * office approval of the timesheet is the control on both. A job that cannot
 * bill its time (shop work, special jobs) shows the tick off and locked, and
 * on a job move billability is the server's rule unless the user set the
 * tick (see billingChangeFields). An entry with no stored times may be edited
 * without imposing a pair; its hours then stay untouched.
 *
 * The form's state lives in WorkshopEntryForm, which DrawerContent unmounts
 * when the drawer closes — so each open seeds from the entry being edited
 * (or the tapped start time), with no reset to run.
 */
export function WorkshopTimesheetEntryDrawer({
  state,
  date,
  dayEntries,
  dayStart,
  saving,
  onCreate,
  onUpdate,
  onDelete,
  onClose,
}: WorkshopTimesheetEntryDrawerProps) {
  const open = state.mode !== 'closed'
  const entry = state.mode === 'edit' ? state.entry : null
  const initialStart = state.mode === 'create' ? state.start : null

  return (
    <Drawer
      open={open}
      onOpenChange={(nowOpen) => {
        // Dismissal is blocked while a write is pending: closing this drawer
        // and opening another entry's would let the first write's completion
        // close the second drawer.
        if (!nowOpen && !saving) onClose()
      }}
    >
      <DrawerContent className="max-h-[90vh]" data-automation-id="WorkshopTimesheetEntryDrawer">
        <div className="mx-auto w-full max-w-md overflow-y-auto">
          <DrawerHeader>
            <DrawerTitle>{entry === null ? 'Add entry' : 'Edit entry'}</DrawerTitle>
            <DrawerDescription>
              {entry === null
                ? `Book your own time for ${formatDateLong(date)}.`
                : `#${entry.job_number} ${entry.job_name} on ${formatDateLong(date)}`}
            </DrawerDescription>
          </DrawerHeader>
          <WorkshopEntryForm
            entry={entry}
            initialStart={initialStart}
            date={date}
            dayEntries={dayEntries}
            dayStart={dayStart}
            saving={saving}
            onCreate={onCreate}
            onUpdate={onUpdate}
            onDelete={onDelete}
            onClose={onClose}
          />
        </div>
      </DrawerContent>
    </Drawer>
  )
}

function WorkshopEntryForm({
  entry,
  initialStart,
  date,
  dayEntries,
  dayStart,
  saving,
  onCreate,
  onUpdate,
  onDelete,
  onClose,
}: Omit<WorkshopTimesheetEntryDrawerProps, 'state'> & {
  entry: WorkshopTimesheetEntryOut | null
  /** The tapped calendar slot a new entry starts from, "HH:mm" or null. */
  initialStart: string | null
}) {
  // A new entry opens on the job last booked and straight after the day's
  // latest finish: the next job usually starts when the last one stopped.
  const [jobId, setJobId] = useState<string | null>(
    () => entry?.job_id ?? lastUsedJobId(dayEntries),
  )
  const [range, setRange] = useState<TimeRange>(() =>
    entry === null
      ? defaultNewEntryRange(dayEntries, dayStart, initialStart)
      : { start: inputTime(entry.start_time), end: inputTime(entry.end_time) },
  )
  const { start, end } = range
  const [rateMultiplier, setRateMultiplier] = useState(entry?.wage_rate_multiplier ?? 1)
  // null until the user touches the tick: only a choice they made is sent on
  // an edit (billingChangeFields).
  const [billableChoice, setBillableChoice] = useState<boolean | null>(null)
  const [description, setDescription] = useState(entry?.description ?? '')

  const jobsQuery = useQuery(timesheetsJobsRetrieveOptions())
  const jobs = useMemo<TimesheetJobOut[]>(() => jobsQuery.data?.jobs ?? [], [jobsQuery.data])
  const selected = jobs.find((job) => job.id === jobId) ?? null
  const sourceJob = entry === null ? null : (jobs.find((job) => job.id === entry.job_id) ?? null)
  const canBill = selected === null || billsItsTime(selected)
  const billable = shownBillable({ entry, sourceJob, selectedJob: selected, billableChoice })
  // A stored rate outside the three offered (set from the office grid) stays
  // selectable, so opening the entry does not silently change it.
  const rateOptions = RATE_OPTIONS.some((option) => option.multiplier === rateMultiplier)
    ? RATE_OPTIONS
    : [...RATE_OPTIONS, { label: rateLabel(rateMultiplier), multiplier: rateMultiplier }]
  const otherEntries = dayEntries.filter((other) => other.id !== entry?.id)

  const hours = deriveHoursFromTimes(start, end)
  // An entry that has no stored times may be saved without a pair — that is
  // the description/job-only edit; entryUpdateBody then leaves hours and
  // times untouched. Creation always needs the pair.
  const untimedEdit =
    entry !== null &&
    entry.start_time === null &&
    entry.end_time === null &&
    start === '' &&
    end === ''
  // A new entry needs a job the list offers: the defaulted last-used job may
  // have been archived since, and its billability is not known until it loads.
  const jobChosen = entry === null ? selected !== null : jobId !== null
  const canSubmit = jobChosen && !saving && (hours !== null || untimedEdit)

  // A ref, not mutation isPending: the disabled state lands on the next
  // render, so a double-click could otherwise book the entry twice.
  const inFlightRef = useRef(false)

  const submit = async () => {
    if (jobId === null || inFlightRef.current) return
    if (hours === null && !untimedEdit) return
    inFlightRef.current = true
    let saved: boolean
    try {
      if (entry === null) {
        if (hours === null) return
        saved = await onCreate({
          job_id: jobId,
          accounting_date: date,
          hours,
          start_time: `${start}:00`,
          end_time: `${end}:00`,
          description: description.trim() === '' ? null : description.trim(),
          is_billable: billable,
          wage_rate_multiplier: rateMultiplier,
        })
      } else {
        saved = await onUpdate({
          ...entryUpdateBody(entry, { jobId, start, end, hours, description }),
          ...billingChangeFields(entry, {
            billableChoice: canBill ? billableChoice : null,
            rateMultiplier,
          }),
        })
      }
    } finally {
      inFlightRef.current = false
    }
    if (saved) onClose()
  }

  const remove = async () => {
    if (entry === null || inFlightRef.current) return
    inFlightRef.current = true
    let deleted: boolean
    try {
      deleted = await onDelete(entry.id)
    } finally {
      inFlightRef.current = false
    }
    if (deleted) onClose()
  }

  return (
    <>
      <div className="space-y-4 px-4 pb-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Job</label>
          <div className="rounded border border-slate-200">
            <JobPicker
              triggerClassName={TOUCH_TARGET_CLASS}
              automationIdPrefix="WorkshopTimesheetEntryDrawer-job-picker"
              ariaLabel="Job"
              jobs={jobs}
              selected={selected}
              disabled={saving}
              loading={jobsQuery.isPending}
              placeholder="Select a job"
              triggerLabel={(job) => {
                if (job) return `#${job.job_number} ${job.name}`
                // A bound job the list no longer offers (archived since)
                // must still show what the entry holds.
                if (entry !== null && jobId === entry.job_id) {
                  return `#${entry.job_number} ${entry.job_name}`
                }
                return ''
              }}
              typedSearchLimit={null}
              commitOnTab={false}
              searchOptions={timesheetJobSearchOptions}
              onSelect={(job) => setJobId(job.id)}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label
              className="mb-1 block text-sm font-medium text-gray-700"
              htmlFor="workshop-entry-start"
            >
              Start
            </label>
            <input
              id="workshop-entry-start"
              type="time"
              value={start}
              className={`${INPUT_CLASS} ${TOUCH_TARGET_CLASS}`}
              data-automation-id="WorkshopTimesheetEntryDrawer-start-time"
              onChange={(event) => setRange({ start: event.target.value, end })}
            />
          </div>
          <div>
            <label
              className="mb-1 block text-sm font-medium text-gray-700"
              htmlFor="workshop-entry-end"
            >
              End
            </label>
            <input
              id="workshop-entry-end"
              type="time"
              value={end}
              className={`${INPUT_CLASS} ${TOUCH_TARGET_CLASS}`}
              data-automation-id="WorkshopTimesheetEntryDrawer-end-time"
              onChange={(event) => setRange({ start, end: event.target.value })}
            />
          </div>
        </div>

        <p
          className="text-sm text-gray-500"
          data-automation-id="WorkshopTimesheetEntryDrawer-duration"
        >
          {hours !== null && `Duration: ${formatHoursDisplay(hours)}`}
          {hours === null &&
            (entry !== null && untimedEdit
              ? `No times recorded — ${formatHoursDisplay(entry.hours)} stays as booked. Add a pair to place it on the calendar.`
              : 'Pick a start and an end time.')}
        </p>

        <div className="flex flex-wrap gap-2" role="group" aria-label="Adjust times">
          <TimeChip id="now" onClick={() => setRange(slotFromNow(new Date()))}>
            Now
          </TimeChip>
          {[-5, 5, 15, 30].map((minutes) => (
            <TimeChip
              key={minutes}
              id={minutes < 0 ? `minus-${-minutes}` : `plus-${minutes}`}
              disabled={start === '' || end === ''}
              onClick={() => setRange(adjustEnd(range, minutes))}
            >
              {minutes < 0 ? `${minutes}m` : `+${minutes}m`}
            </TimeChip>
          ))}
          <TimeChip
            id="fill-gap"
            disabled={start === ''}
            onClick={() => setRange(fillGapToNextEntry(start, otherEntries))}
          >
            Fill gap
          </TimeChip>
          <TimeChip id="reset" onClick={() => setRange(slotFrom(dayStart))}>
            Reset
          </TimeChip>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label
              className="mb-1 block text-sm font-medium text-gray-700"
              htmlFor="workshop-entry-rate"
            >
              Rate
            </label>
            <select
              id="workshop-entry-rate"
              value={rateMultiplier}
              className={`${INPUT_CLASS} ${TOUCH_TARGET_CLASS}`}
              data-automation-id="WorkshopTimesheetEntryDrawer-rate"
              onChange={(event) => setRateMultiplier(Number(event.target.value))}
            >
              {rateOptions.map((option) => (
                <option key={option.multiplier} value={option.multiplier}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <span className="mb-1 block text-sm font-medium text-gray-700">Billing</span>
            <label className={`${TOUCH_TARGET_CLASS} flex items-center gap-2 text-sm`}>
              <input
                type="checkbox"
                className="size-5"
                checked={billable}
                disabled={!canBill}
                data-automation-id="WorkshopTimesheetEntryDrawer-billable"
                onChange={(event) => setBillableChoice(event.target.checked)}
              />
              Billable
            </label>
          </div>
        </div>

        <div>
          <label
            className="mb-1 block text-sm font-medium text-gray-700"
            htmlFor="workshop-entry-description"
          >
            Description
          </label>
          <textarea
            id="workshop-entry-description"
            value={description}
            rows={3}
            maxLength={255}
            placeholder="What was done"
            className={INPUT_CLASS}
            data-automation-id="WorkshopTimesheetEntryDrawer-description"
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
      </div>

      <DrawerFooter>
        <div className="flex items-center gap-2">
          <Button
            className={`flex-1 ${TOUCH_TARGET_CLASS}`}
            disabled={!canSubmit}
            data-automation-id="WorkshopTimesheetEntryDrawer-submit"
            onClick={() => void submit()}
          >
            {entry === null ? 'Add entry' : 'Save changes'}
          </Button>
          <Button
            variant="outline"
            className={TOUCH_TARGET_CLASS}
            disabled={saving}
            data-automation-id="WorkshopTimesheetEntryDrawer-cancel"
            onClick={onClose}
          >
            Cancel
          </Button>
          {entry !== null && (
            <Button
              variant="destructive"
              className={TOUCH_TARGET_CLASS}
              disabled={saving}
              data-automation-id="WorkshopTimesheetEntryDrawer-delete"
              onClick={() => void remove()}
            >
              Delete
            </Button>
          )}
        </div>
      </DrawerFooter>
    </>
  )
}

/** One quick-adjust chip: a single tap moves the times instead of the time
    pickers being opened again. */
function TimeChip({
  id,
  disabled = false,
  onClick,
  children,
}: {
  id: string
  disabled?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      className={`${TOUCH_TARGET_CLASS} justify-center rounded-full border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50 disabled:opacity-50`}
      data-automation-id={`WorkshopTimesheetEntryDrawer-chip-${id}`}
      onClick={onClick}
    >
      {children}
    </button>
  )
}
