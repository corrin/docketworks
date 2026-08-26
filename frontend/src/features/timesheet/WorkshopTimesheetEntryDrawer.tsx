import { useEffect, useMemo, useState } from 'react'
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

import { formatHoursDisplay } from './hours'
import { deriveHoursFromTimes } from './myTime'
import { useTimesheetJobSearch } from './useTimesheetJobSearch'

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
 * Hours are always derived from the time pair (the server refuses a trio
 * that disagrees), so the drawer shows the duration instead of asking for
 * it, and a shop job books non-billable because billable shop time is
 * refused at the model.
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

  const [jobId, setJobId] = useState<string | null>(null)
  const [shopJob, setShopJob] = useState(false)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [description, setDescription] = useState('')

  // Reset per open, not per render: the drawer keeps a half-typed form only
  // while it stays open.
  useEffect(() => {
    if (state.mode === 'create') {
      setJobId(null)
      setShopJob(false)
      setStart(state.start ?? '')
      setEnd('')
      setDescription('')
    } else if (state.mode === 'edit') {
      setJobId(state.entry.job_id)
      setShopJob(false)
      setStart(inputTime(state.entry.start_time))
      setEnd(inputTime(state.entry.end_time))
      setDescription(state.entry.description)
    }
  }, [state])

  const jobsQuery = useQuery({ ...timesheetsJobsRetrieveOptions(), enabled: open })
  const jobs = useMemo<TimesheetJobOut[]>(() => jobsQuery.data?.jobs ?? [], [jobsQuery.data])
  const selected = jobs.find((job) => job.id === jobId) ?? null

  const hours = deriveHoursFromTimes(start, end)
  const canSubmit = jobId !== null && hours !== null && !saving

  const submit = async () => {
    if (jobId === null || hours === null) return
    let saved: boolean
    if (entry === null) {
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
      saved = await onUpdate({
        entry_id: entry.id,
        // The job field is only a move when it actually changed.
        ...(jobId === entry.job_id ? {} : { job_id: jobId }),
        hours,
        start_time: `${start}:00`,
        end_time: `${end}:00`,
        description: description.trim() === '' ? null : description.trim(),
      })
    }
    if (saved) onClose()
  }

  const remove = async () => {
    if (entry === null) return
    if (await onDelete(entry.id)) onClose()
  }

  return (
    <Drawer
      open={open}
      onOpenChange={(nowOpen) => {
        if (!nowOpen) onClose()
      }}
    >
      <DrawerContent className="max-h-[90vh]">
        <div className="mx-auto w-full max-w-md overflow-y-auto">
          <DrawerHeader>
            <DrawerTitle>{entry === null ? 'Add entry' : 'Edit entry'}</DrawerTitle>
            <DrawerDescription>
              {entry === null
                ? 'Book your own time against a job.'
                : `#${entry.job_number} ${entry.job_name}`}
            </DrawerDescription>
          </DrawerHeader>

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
                  useJobSearch={useTimesheetJobSearch}
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
              {hours === null
                ? 'Pick a start and an end time.'
                : `Duration: ${formatHoursDisplay(hours)}`}
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
        </div>
      </DrawerContent>
    </Drawer>
  )
}
