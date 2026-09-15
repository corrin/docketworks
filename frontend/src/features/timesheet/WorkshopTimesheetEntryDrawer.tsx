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
import { JobPicker } from '@/features/shared/JobPicker'

import { formatHoursDisplay } from '@/lib/format'
import { deriveHoursFromTimes, entryUpdateBody } from './myTime'
import { timesheetJobSearchOptions } from './timesheetJobSearch'

export type EntryDrawerState =
  | { mode: 'closed' }
  | { mode: 'create'; start: string | null }
  | { mode: 'edit'; entry: WorkshopTimesheetEntryOut }

interface WorkshopTimesheetEntryDrawerProps {
  state: EntryDrawerState
  /** The day new entries book to, YYYY-MM-DD. */
  date: string
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
 * Add/edit drawer for one workshop entry: job, start/end time, description.
 *
 * Fable: Hours are always derived from the time pair (the server refuses a
 * trio that disagrees), so the drawer shows the duration instead of asking
 * for it. Billability follows the job type on create and on any job move —
 * billable shop time is refused at the model. An entry with no stored times
 * may be edited without imposing a pair; its hours then stay untouched.
 *
 * The form's state lives in WorkshopEntryForm, which DrawerContent unmounts
 * when the drawer closes — so each open seeds from the entry being edited
 * (or the tapped start time), with no reset to run.
 */
export function WorkshopTimesheetEntryDrawer({
  state,
  date,
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
                ? 'Book your own time against a job.'
                : `#${entry.job_number} ${entry.job_name}`}
            </DrawerDescription>
          </DrawerHeader>
          <WorkshopEntryForm
            entry={entry}
            initialStart={initialStart}
            date={date}
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
  const [jobId, setJobId] = useState<string | null>(entry?.job_id ?? null)
  const [shopJob, setShopJob] = useState(false)
  const [start, setStart] = useState(
    entry === null ? (initialStart ?? '') : inputTime(entry.start_time),
  )
  const [end, setEnd] = useState(entry === null ? '' : inputTime(entry.end_time))
  const [description, setDescription] = useState(entry?.description ?? '')

  const jobsQuery = useQuery(timesheetsJobsRetrieveOptions())
  const jobs = useMemo<TimesheetJobOut[]>(() => jobsQuery.data?.jobs ?? [], [jobsQuery.data])
  const selected = jobs.find((job) => job.id === jobId) ?? null

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
  const canSubmit = jobId !== null && !saving && (hours !== null || untimedEdit)

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
          is_billable: !shopJob,
        })
      } else {
        saved = await onUpdate(
          entryUpdateBody(entry, { jobId, shopJob, start, end, hours, description }),
        )
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
              onSelect={(job) => {
                setJobId(job.id)
                setShopJob(job.shop_job)
              }}
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
              className="h-9 w-full rounded border border-slate-200 px-2 text-sm"
              data-automation-id="WorkshopTimesheetEntryDrawer-start-time"
              onChange={(event) => setStart(event.target.value)}
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
              className="h-9 w-full rounded border border-slate-200 px-2 text-sm"
              data-automation-id="WorkshopTimesheetEntryDrawer-end-time"
              onChange={(event) => setEnd(event.target.value)}
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
            className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
            data-automation-id="WorkshopTimesheetEntryDrawer-description"
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
      </div>

      <DrawerFooter>
        <div className="flex items-center gap-2">
          <Button
            className="flex-1"
            disabled={!canSubmit}
            data-automation-id="WorkshopTimesheetEntryDrawer-submit"
            onClick={() => void submit()}
          >
            {entry === null ? 'Add entry' : 'Save changes'}
          </Button>
          <Button
            variant="outline"
            disabled={saving}
            data-automation-id="WorkshopTimesheetEntryDrawer-cancel"
            onClick={onClose}
          >
            Cancel
          </Button>
          {entry !== null && (
            <Button
              variant="destructive"
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
