import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronLeft, ChevronRight, Pencil, Plus } from 'lucide-react'
import { Fragment, useState } from 'react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  timesheetsApprovalsApproveDayMutation,
  timesheetsApprovalsRetrieveOptions,
  timesheetsApprovalsRetrieveQueryKey,
} from '@/api'
import type { StaffApprovalOut, WorkshopTimesheetEntryOut } from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { companyDefaultsQueryOptions } from '@/features/shell'
import { shiftDate } from '@/lib/dates'
import { formatDateLong, formatHoursDisplay } from '@/lib/format'

import { ClockTimesForm } from './DayCard'
import { cautionMarks, clockWords, entryMarks, workingDayStart } from './myTime'
import { useClocking, useWorkshopEntryWrites } from './useWorkshopDay'
import { WorkshopTimesheetEntryDrawer, type EntryDrawerState } from './WorkshopTimesheetEntryDrawer'

export interface ApproveTimeSearch {
  date?: string
}

interface ApproveTimePageProps {
  /** The route has already written the date into the URL, so it is never missing. */
  search: Required<ApproveTimeSearch>
  onDateChange: (date: string) => void
}

/** What each state asks of the office, in words: state never rests on colour. */
const STATE_WORDS: Record<StaffApprovalOut['state'], string> = {
  waiting: 'Waiting for approval',
  nothing_entered: 'Nothing entered',
  nothing_waiting: 'Approved',
}

/** Who the entry drawer is open for; the drawer itself only knows the entry. */
type Correction = { staffId: string; drawer: EntryDrawerState }

/**
 * Approve time: the office's one screen for the day's timesheets (KAN-376).
 * Any office staff member approves here, so it shows hours and never pay.
 *
 * The server orders the people: time waiting first, then nothing entered,
 * then days already dealt with, so the list opens on what needs doing.
 * A person's entries open under their row; an entry is corrected in the same
 * drawer the worker used, because the office corrects and phones the worker,
 * it does not send the entry back.
 */
export function ApproveTimePage({ search, onDateChange }: ApproveTimePageProps) {
  const { date } = search
  const queryClient = useQueryClient()
  const approvalsQuery = useQuery(timesheetsApprovalsRetrieveOptions({ query: { date } }))
  const { data: companyDefaults } = useSuspenseQuery(companyDefaultsQueryOptions())
  const approveDay = useMutation(timesheetsApprovalsApproveDayMutation())
  const [openStaffId, setOpenStaffId] = useState<string | null>(null)
  const [correction, setCorrection] = useState<Correction | null>(null)
  // Office staff are never asked where they are: the remote mark is about a
  // worker's own save.
  const writes = useWorkshopEntryWrites(false, correction?.staffId)
  // Whose clock times the office has open for correction, if anyone's.
  const [clockStaffId, setClockStaffId] = useState<string | null>(null)
  const clocking = useClocking(clockStaffId ?? undefined)

  const people = approvalsQuery.data?.staff
  const correcting = people?.find((person) => person.staff_id === correction?.staffId)

  const approve = async (person: StaffApprovalOut) => {
    try {
      await approveDay.mutateAsync({ path: { staff_id: person.staff_id, target_date: date } })
    } catch (error) {
      toast.error(apiErrorMessage(error, `${person.staff_name}'s day could not be approved.`))
      return
    }
    toast.success(`${person.staff_name}'s day approved.`)
    void queryClient.invalidateQueries({ queryKey: timesheetsApprovalsRetrieveQueryKey() })
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-gray-900">Approve time</h1>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            aria-label="Previous day"
            data-automation-id="ApproveTimePage-previous-day"
            onClick={() => onDateChange(shiftDate(date, -1))}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <input
            type="date"
            value={date}
            aria-label="Date"
            className="rounded border border-slate-200 px-2 py-1 text-sm"
            data-automation-id="ApproveTimePage-date"
            onChange={(event) => {
              if (event.target.value) onDateChange(event.target.value)
            }}
          />
          <Button
            variant="outline"
            size="sm"
            aria-label="Next day"
            data-automation-id="ApproveTimePage-next-day"
            onClick={() => onDateChange(shiftDate(date, 1))}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <p className="text-sm text-slate-600">
        {formatDateLong(date)}. Staff are paid for approved time only.
      </p>

      <ListTable
        isPending={approvalsQuery.isPending}
        isError={approvalsQuery.isError}
        onRetry={() => void approvalsQuery.refetch()}
        loadingLabel="Loading the day's timesheets..."
        errorLabel="Failed to load the day's timesheets."
        rows={people}
        emptyLabel="Nobody is on the timesheet for this day."
        automationId="ApproveTimePage-table"
        head={
          <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-600">
            <th className="px-2 py-2">Staff member</th>
            <th className="hidden px-2 py-2 sm:table-cell">Clock</th>
            <th className="w-24 px-2 py-2">Entered</th>
            <th className="w-24 px-2 py-2">Waiting</th>
            <th className="px-2 py-2">State</th>
            <th className="w-36 px-2 py-2" />
          </tr>
        }
        renderRow={(person) => (
          <Fragment key={person.staff_id}>
            <tr
              className="border-b border-slate-100"
              data-automation-id={`ApproveTimePage-row-${person.staff_id}`}
            >
              <td className="px-2 py-2">
                <button
                  type="button"
                  className="flex items-center gap-1 text-left font-medium text-slate-900 hover:underline"
                  aria-expanded={openStaffId === person.staff_id}
                  data-automation-id={`ApproveTimePage-open-${person.staff_id}`}
                  onClick={() =>
                    setOpenStaffId(openStaffId === person.staff_id ? null : person.staff_id)
                  }
                >
                  {openStaffId === person.staff_id ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                  {person.staff_name}
                </button>
                <div
                  className="pl-5 text-xs text-slate-600 sm:hidden"
                  data-automation-id={`ApproveTimePage-clock-narrow-${person.staff_id}`}
                >
                  {clockWords(person.clock)}
                </div>
              </td>
              {/* On a phone the clock words sit under the name (below), so the
                  state and the Approve day button stay in view without a swipe. */}
              <td
                className="hidden px-2 py-2 text-slate-700 sm:table-cell"
                data-automation-id={`ApproveTimePage-clock-${person.staff_id}`}
              >
                {clockWords(person.clock)}
              </td>
              <td className="px-2 py-2">{formatHoursDisplay(person.entered_hours)}</td>
              <td
                className="px-2 py-2"
                data-automation-id={`ApproveTimePage-waiting-${person.staff_id}`}
              >
                {formatHoursDisplay(person.waiting_hours)}
              </td>
              <td
                className="px-2 py-2"
                data-automation-id={`ApproveTimePage-state-${person.staff_id}`}
              >
                <span className={person.state === 'waiting' ? 'font-semibold' : 'text-slate-600'}>
                  {STATE_WORDS[person.state]}
                </span>
                {cautionMarks({ ...person, sent_late: person.clock.sent_late }).map((mark) => (
                  <span key={mark} className="ml-2 font-semibold text-amber-800">
                    {mark}
                  </span>
                ))}
              </td>
              <td className="px-2 py-2 text-right">
                {person.state === 'waiting' && (
                  <Button
                    size="sm"
                    disabled={approveDay.isPending}
                    data-automation-id={`ApproveTimePage-approve-${person.staff_id}`}
                    onClick={() => void approve(person)}
                  >
                    Approve day
                  </Button>
                )}
              </td>
            </tr>
            {openStaffId === person.staff_id && (
              <tr className="border-b border-slate-100 bg-slate-50/60">
                <td colSpan={6} className="space-y-3 px-2 py-2 pl-8">
                  {clockStaffId === person.staff_id ? (
                    <ClockTimesForm
                      automationId={`ApproveTimePage-clock-${person.staff_id}`}
                      day={person.clock}
                      defaultStart={workingDayStart(date, companyDefaults)}
                      saving={clocking.clocking}
                      onSave={(clockIn, clockOut) =>
                        clocking.setTimes({ date, clock_in: clockIn, clock_out: clockOut })
                      }
                      onCancel={() => setClockStaffId(null)}
                    />
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      data-automation-id={`ApproveTimePage-clock-edit-${person.staff_id}`}
                      onClick={() => setClockStaffId(person.staff_id)}
                    >
                      <Pencil className="h-4 w-4" /> Correct clock times
                    </Button>
                  )}
                  <PersonEntries
                    person={person}
                    onEdit={(entry) =>
                      setCorrection({ staffId: person.staff_id, drawer: { mode: 'edit', entry } })
                    }
                    onAdd={() =>
                      setCorrection({
                        staffId: person.staff_id,
                        drawer: { mode: 'create', start: null },
                      })
                    }
                  />
                </td>
              </tr>
            )}
          </Fragment>
        )}
      />

      <WorkshopTimesheetEntryDrawer
        state={correction?.drawer ?? { mode: 'closed' }}
        // Approved time is locked for the worker, never for the office.
        locked={false}
        date={date}
        dayEntries={correcting?.entries ?? []}
        dayStart={workingDayStart(date, companyDefaults)}
        saving={writes.saving}
        onCreate={writes.createEntry}
        onUpdate={writes.updateEntry}
        onDelete={writes.deleteEntry}
        onClose={() => setCorrection(null)}
      />
    </div>
  )
}

/** One person's entries for the day, each open to correction. */
function PersonEntries({
  person,
  onEdit,
  onAdd,
}: {
  person: StaffApprovalOut
  onEdit: (entry: WorkshopTimesheetEntryOut) => void
  onAdd: () => void
}) {
  return (
    <div className="space-y-2" data-automation-id={`ApproveTimePage-entries-${person.staff_id}`}>
      {person.entries.length === 0 && (
        <p className="text-sm text-slate-600">Nothing entered for this day.</p>
      )}
      <ul className="divide-y divide-slate-100">
        {person.entries.map((entry) => (
          <li
            key={entry.id}
            className="flex flex-wrap items-center justify-between gap-2 py-1 text-sm"
            data-automation-id={`ApproveTimePage-entry-${entry.id}`}
          >
            <div className="min-w-0">
              <span className="font-medium text-slate-900">
                #{entry.job_number} {entry.job_name}
              </span>
              {entry.description !== '' && (
                <span className="ml-2 text-slate-600">{entry.description}</span>
              )}
              <span className="ml-2 text-xs font-semibold text-slate-700">
                {entryMarks(entry).join(' · ')}
              </span>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {entry.start_time !== null && entry.end_time !== null && (
                <span className="text-xs text-slate-600">
                  {entry.start_time.slice(0, 5)} to {entry.end_time.slice(0, 5)}
                </span>
              )}
              <span className="font-medium">{formatHoursDisplay(entry.hours)}</span>
              <Button
                variant="outline"
                size="sm"
                aria-label={`Correct entry on job ${entry.job_number}`}
                data-automation-id={`ApproveTimePage-edit-${entry.id}`}
                onClick={() => onEdit(entry)}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <Button
        variant="outline"
        size="sm"
        data-automation-id={`ApproveTimePage-add-${person.staff_id}`}
        onClick={onAdd}
      >
        <Plus className="h-4 w-4" /> Add entry
      </Button>
    </div>
  )
}
