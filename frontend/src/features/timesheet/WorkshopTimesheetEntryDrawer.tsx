import { useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  timesheetsJobsRetrieveOptions,
  timesheetsMyDayPlacementOptions,
} from '@/api'
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
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from '@/features/shared/useDebouncedValue'

import { formatDateLong, formatHoursDisplay } from '@/lib/format'
import {
  adjustEnd,
  billingChangeFields,
  billsItsTime,
  entryTimeFields,
  entryUpdateBody,
  fillGapToNextEntry,
  lastUsedJobId,
  rateOptionsFor,
  resolveSelectedJob,
  shownBillable,
  slotFrom,
  slotFromNow,
  type EntryFormValues,
  type TimeRange,
} from './myTime'
import { timesheetJobSearchOptions } from './timesheetJobSearch'

export type EntryDrawerState =
  | { mode: 'closed' }
  | { mode: 'create'; start: string | null }
  | { mode: 'edit'; entry: WorkshopTimesheetEntryOut }

interface WorkshopTimesheetEntryDrawerProps {
  state: EntryDrawerState
  /** The entry is approved and this person may not change it: it is shown,
      not edited. */
  locked: boolean
  /** The day new entries book to, YYYY-MM-DD. */
  date: string
  /** Every entry already on that day: a new entry defaults its job and start
      from them, and "Fill gap" runs up to the next one. */
  dayEntries: WorkshopTimesheetEntryOut[]
  /** Where a new entry starts, "HH:mm": after the day's last entry, else the
      clock-in, else the working day, as the server works it out. */
  dayStart: string
  /** When his day ends, "HH:mm": the clock-out, else the standard finish;
      null on a day with neither. "Fill gap" stops there. */
  dayEnd: string | null
  /** Whose time it is when the office is correcting someone's day; the
      caller's own when absent. The placement is worked out around their breaks. */
  ownerId?: string
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
 * Add/edit drawer for one workshop entry: job, hours, start/finish, rate,
 * billable, description.
 *
 * Hours are what he is paid and the job is billed; the times are their
 * picture on the calendar and optional. Breaks are outside job time, so
 * the two are related through the day's breaks and only the server knows
 * them: given hours, it works out the finish; given a finish, the hours.
 * Workshop staff choose the rate and whether the time is billable; office
 * approval of the timesheet is the control on both. A job that cannot bill
 * its time (shop work, special jobs) shows the tick off and locked, and on a
 * job move billability is the server's rule unless the user set the tick
 * (see billingChangeFields).
 *
 * The form's state lives in WorkshopEntryForm, which DrawerContent unmounts
 * when the drawer closes — so each open seeds from the entry being edited
 * (or the tapped start time), with no reset to run.
 */
export function WorkshopTimesheetEntryDrawer({
  state,
  locked,
  date,
  dayEntries,
  dayStart,
  dayEnd,
  ownerId,
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
            <DrawerTitle>{drawerTitle(entry, locked)}</DrawerTitle>
            <DrawerDescription>
              {entry === null
                ? `Book your own time for ${formatDateLong(date)}.`
                : `#${entry.job_number} ${entry.job_name} on ${formatDateLong(date)}`}
            </DrawerDescription>
          </DrawerHeader>
          <WorkshopEntryForm
            entry={entry}
            locked={locked}
            initialStart={initialStart}
            date={date}
            dayEntries={dayEntries}
            dayStart={dayStart}
            dayEnd={dayEnd}
            ownerId={ownerId}
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

function drawerTitle(entry: WorkshopTimesheetEntryOut | null, locked: boolean): string {
  if (entry === null) return 'Add entry'
  if (locked) return 'Approved entry'
  return 'Edit entry'
}

/**
 * Which of the three values was given last, and so which one the server is
 * working out: the finish from the hours, or the hours from the finish. Null
 * while the form holds what was stored, or a new entry no one has sized.
 */
type WorkingOut = 'finish' | 'hours' | null

function WorkshopEntryForm({
  entry,
  locked,
  initialStart,
  date,
  dayEntries,
  dayStart,
  dayEnd,
  ownerId,
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
  // A new entry opens on the job last booked and starts where the day is up
  // to (the tapped slot, else after the last entry): the hours are his to say.
  const [jobId, setJobId] = useState<string | null>(
    () => entry?.job_id ?? lastUsedJobId(dayEntries),
  )
  const [hours, setHours] = useState<number | null>(entry === null ? null : entry.hours)
  const [start, setStart] = useState(
    entry === null ? (initialStart ?? dayStart) : inputTime(entry.start_time),
  )
  const [end, setEnd] = useState(entry === null ? '' : inputTime(entry.end_time))
  const [workingOut, setWorkingOut] = useState<WorkingOut>(null)
  const [rateMultiplier, setRateMultiplier] = useState(entry?.wage_rate_multiplier ?? 1)
  // null until the user touches the tick: only a choice they made is sent on
  // an edit (billingChangeFields).
  const [billableChoice, setBillableChoice] = useState<boolean | null>(null)
  const [description, setDescription] = useState(entry?.description ?? '')

  const jobsQuery = useQuery(timesheetsJobsRetrieveOptions())
  const jobs = useMemo<TimesheetJobOut[]>(() => jobsQuery.data?.jobs ?? [], [jobsQuery.data])
  // The job as the picker handed it over: one found through its whole-table
  // search is not in `jobs`.
  const [pickedJob, setPickedJob] = useState<TimesheetJobOut | null>(null)
  const selected = resolveSelectedJob(pickedJob, jobs, jobId)
  const sourceJob = entry === null ? null : (jobs.find((job) => job.id === entry.job_id) ?? null)
  const canBill = selected === null || billsItsTime(selected)
  const billable = shownBillable({ entry, sourceJob, selectedJob: selected, billableChoice })
  const rateOptions = rateOptionsFor(entry === null ? null : entry.wage_rate_multiplier)
  const otherEntries = dayEntries.filter((other) => other.id !== entry?.id)
  const gap = start === '' ? null : fillGapToNextEntry(start, otherEntries, dayEnd)

  // The server's answer as he types, a pause after each change; the one
  // placement rule (apps/timesheet/services/attendance.finish_for), never
  // worked out here.
  const asked = useDebouncedValue({ start, hours, end, workingOut }, SEARCH_DEBOUNCE_MS)
  const placementQuery = useQuery({
    ...timesheetsMyDayPlacementOptions({ query: placementQuestion(date, asked, ownerId) }),
    enabled: placementAskable(asked),
  })
  const settled =
    asked.start === start &&
    asked.hours === hours &&
    asked.end === end &&
    asked.workingOut === workingOut
  const placement = settled && placementQuery.data !== undefined ? placementQuery.data : null
  // What the fields show: the typed value on the side he typed, the server's
  // on the other, blank while it is still being worked out.
  const shownEnd =
    workingOut === 'hours' ? (placement === null ? '' : inputTime(placement.finish)) : end
  const shownHours = workingOut === 'finish' ? (placement?.hours ?? null) : hours

  const queryClient = useQueryClient()
  // A new entry needs a job the drawer actually holds: the defaulted last-used
  // job may have been archived since, and its billability is not known until
  // the list loads. A job the user picked is always held.
  const jobChosen = entry === null ? selected !== null : jobId !== null
  const sized = workingOut === 'finish' ? start !== '' && end !== '' : hours !== null && hours > 0
  const canSubmit = jobChosen && !saving && sized

  // A ref, not mutation isPending: the disabled state lands on the next
  // render, so a double-click could otherwise book the entry twice.
  const inFlightRef = useRef(false)

  /** The three values as they will be saved: the server's answer is waited
      for rather than guessed, so a quick Save after typing is still right. */
  const resolveTimes = async (): Promise<Pick<
    EntryFormValues,
    'hours' | 'start' | 'end'
  > | null> => {
    const question = { start, hours, end, workingOut }
    if (!placementAskable(question)) {
      return hours === null ? null : { hours, start, end }
    }
    const answer = await queryClient.fetchQuery(
      timesheetsMyDayPlacementOptions({ query: placementQuestion(date, question, ownerId) }),
    )
    return { hours: answer.hours, start, end: inputTime(answer.finish) }
  }

  const submit = async () => {
    if (jobId === null || inFlightRef.current) return
    inFlightRef.current = true
    let saved: boolean
    try {
      const times = await resolveTimes()
      if (times === null) return
      if (entry === null) {
        saved = await onCreate({
          job_id: jobId,
          accounting_date: date,
          ...entryTimeFields(times),
          description: description.trim() === '' ? null : description.trim(),
          is_billable: billable,
          wage_rate_multiplier: rateMultiplier,
        })
      } else {
        saved = await onUpdate({
          ...entryUpdateBody(entry, { jobId, ...times, description }),
          ...billingChangeFields(entry, {
            billableChoice: canBill ? billableChoice : null,
            rateMultiplier,
          }),
        })
      }
    } catch (error) {
      toast.error(apiErrorMessage(error, 'The times could not be worked out.'))
      return
    } finally {
      inFlightRef.current = false
    }
    if (saved) onClose()
  }

  /** A chip or a typed finish: the finish is now the given value and the hours follow. */
  const setTimes = (range: TimeRange) => {
    setStart(range.start)
    setEnd(range.end)
    setWorkingOut('finish')
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
      {locked && (
        <p
          className="mx-4 mb-2 rounded bg-slate-100 p-2 text-sm text-slate-700"
          data-automation-id="WorkshopTimesheetEntryDrawer-locked"
        >
          The office has approved this entry. Ask the office to change it.
        </p>
      )}
      {/* A disabled fieldset disables every control inside it, so an approved
          entry reads exactly as it was saved and nothing can be typed. */}
      <fieldset disabled={locked} className="space-y-4 px-4 pb-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Job</label>
          <div className="rounded border border-slate-200">
            <JobPicker
              triggerClassName={TOUCH_TARGET_CLASS}
              automationIdPrefix="WorkshopTimesheetEntryDrawer-job-picker"
              ariaLabel="Job"
              jobs={jobs}
              selected={selected}
              disabled={saving || locked}
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
              onSelect={(job) => {
                setJobId(job.id)
                setPickedJob(job)
              }}
            />
          </div>
        </div>

        <div>
          <label
            className="mb-1 block text-sm font-medium text-gray-700"
            htmlFor="workshop-entry-hours"
          >
            Hours
          </label>
          <input
            id="workshop-entry-hours"
            type="number"
            inputMode="decimal"
            min={0.25}
            step={0.25}
            value={shownHours ?? ''}
            placeholder={workingOut === 'finish' ? 'Working out…' : 'How long?'}
            className={`${INPUT_CLASS} ${TOUCH_TARGET_CLASS}`}
            data-automation-id="WorkshopTimesheetEntryDrawer-hours"
            onChange={(event) => {
              setHours(event.target.value === '' ? null : Number(event.target.value))
              setWorkingOut('hours')
            }}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label
              className="mb-1 block text-sm font-medium text-gray-700"
              htmlFor="workshop-entry-start"
            >
              Start <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <input
              id="workshop-entry-start"
              type="time"
              value={start}
              className={`${INPUT_CLASS} ${TOUCH_TARGET_CLASS}`}
              data-automation-id="WorkshopTimesheetEntryDrawer-start-time"
              onChange={(event) => {
                setStart(event.target.value)
                // The hours are the truth: a moved start moves the finish with them.
                if (hours !== null) setWorkingOut('hours')
              }}
            />
          </div>
          <div>
            <label
              className="mb-1 block text-sm font-medium text-gray-700"
              htmlFor="workshop-entry-end"
            >
              Finish <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <input
              id="workshop-entry-end"
              type="time"
              value={shownEnd}
              placeholder={workingOut === 'hours' ? 'Working out…' : ''}
              className={`${INPUT_CLASS} ${TOUCH_TARGET_CLASS}`}
              data-automation-id="WorkshopTimesheetEntryDrawer-end-time"
              onChange={(event) => {
                setEnd(event.target.value)
                setWorkingOut('finish')
              }}
            />
          </div>
        </div>

        <p
          className="text-sm text-gray-500"
          data-automation-id="WorkshopTimesheetEntryDrawer-duration"
        >
          {placementWords(start, shownHours, shownEnd, workingOut)}
        </p>

        <div className="flex flex-wrap gap-2" role="group" aria-label="Adjust times">
          <TimeChip id="now" onClick={() => setTimes(slotFromNow(new Date()))}>
            Now
          </TimeChip>
          {[-5, 5, 15, 30].map((minutes) => (
            <TimeChip
              key={minutes}
              id={minutes < 0 ? `minus-${-minutes}` : `plus-${minutes}`}
              disabled={start === '' || shownEnd === ''}
              onClick={() => setTimes(adjustEnd({ start, end: shownEnd }, minutes))}
            >
              {minutes < 0 ? `${minutes}m` : `+${minutes}m`}
            </TimeChip>
          ))}
          <TimeChip
            id="fill-gap"
            disabled={gap === null}
            onClick={() => {
              if (gap !== null) setTimes(gap)
            }}
          >
            Fill gap
          </TimeChip>
          <TimeChip id="reset" onClick={() => setTimes(slotFrom(dayStart))}>
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
      </fieldset>

      <DrawerFooter>
        <div className="flex items-center gap-2">
          {!locked && (
            <Button
              className={`flex-1 ${TOUCH_TARGET_CLASS}`}
              disabled={!canSubmit}
              data-automation-id="WorkshopTimesheetEntryDrawer-submit"
              onClick={() => void submit()}
            >
              {entry === null ? 'Add entry' : 'Save changes'}
            </Button>
          )}
          <Button
            variant="outline"
            className={TOUCH_TARGET_CLASS}
            disabled={saving}
            data-automation-id="WorkshopTimesheetEntryDrawer-cancel"
            onClick={onClose}
          >
            {locked ? 'Close' : 'Cancel'}
          </Button>
          {entry !== null && !locked && (
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

type PlacementQuestion = {
  start: string
  hours: number | null
  end: string
  workingOut: WorkingOut
}

/** Whether there is something for the server to work out: a start and the
    value on the side he gave. */
function placementAskable(question: PlacementQuestion): boolean {
  if (question.start === '') return false
  if (question.workingOut === 'hours') return question.hours !== null && question.hours > 0
  if (question.workingOut === 'finish') return question.end !== ''
  return false
}

/** The placement endpoint's query for the question, which placementAskable has passed. */
function placementQuestion(date: string, question: PlacementQuestion, ownerId: string | undefined) {
  return {
    date,
    start: `${question.start}:00`,
    ...(question.workingOut === 'hours'
      ? { hours: question.hours }
      : { finish: `${question.end}:00` }),
    ...(ownerId === undefined ? {} : { staff_id: ownerId }),
  }
}

/** The line under the fields: what the entry comes to, and what is being worked out. */
function placementWords(
  start: string,
  hours: number | null,
  end: string,
  workingOut: WorkingOut,
): string {
  if (workingOut === 'hours' && start !== '' && hours !== null && end === '')
    return 'Working out the finish from the hours and your breaks…'
  if (workingOut === 'finish' && start !== '' && end !== '' && hours === null)
    return 'Working out the hours from the times and your breaks…'
  if (hours === null) return 'Say how long it took. The times are optional.'
  if (start === '' || end === '')
    return `${formatHoursDisplay(hours)}, placed after your last entry when you save.`
  return `${formatHoursDisplay(hours)} from ${start} to ${end}, breaks left out.`
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
