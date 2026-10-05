import { useSuspenseQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'

import type { WorkshopTimesheetEntryOut } from '@/api'
import { Button } from '@/components/ui/button'
import { TOUCH_TARGET_CLASS } from '@/components/ui/touch'
import { meQueryOptions } from '@/features/auth'
import { QueryState } from '@/features/shared/QueryState'
import { SummaryCard } from '@/features/shared/SummaryCard'
import { companyDefaultsQueryOptions } from '@/features/shell'
import { formatDateLong, formatHoursDisplay, localIsoDate } from '@/lib/format'
import { shiftDate } from '@/lib/dates'

import {
  calendarEvent,
  distinctJobCount,
  entryLockedFor,
  entryMarks,
  rateLabel,
  splitDayEntries,
  workingDayStart,
} from './myTime'
import { DayCard } from './DayCard'
import { useClocking, useWorkshopDay } from './useWorkshopDay'
import { WorkshopTimesheetCalendar } from './WorkshopTimesheetCalendar'
import { WorkshopTimesheetEntryDrawer, type EntryDrawerState } from './WorkshopTimesheetEntryDrawer'

export interface MyTimeSearch {
  date?: string
}

interface WorkshopMyTimePageProps {
  search: MyTimeSearch
  onDateChange: (date: string) => void
}

/**
 * The workshop "my time" page: one staff member's own day as a calendar.
 *
 * The one timesheet surface open to ordinary workshop staff — the server
 * scopes every read and write to the authenticated staff member, so the page
 * carries no staff selector. Entries without a full time pair cannot sit on
 * the time grid and list below it instead, still open to edit.
 */
export function WorkshopMyTimePage({ search, onDateChange }: WorkshopMyTimePageProps) {
  const date = search.date ?? localIsoDate()
  // Already in the cache: the shell loads the company defaults before any
  // authed route renders.
  const { data: companyDefaults } = useSuspenseQuery(companyDefaultsQueryOptions())
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const day = useWorkshopDay(date, companyDefaults.latitude !== null && !user.is_office_staff)
  const [drawer, setDrawer] = useState<EntryDrawerState>({ mode: 'closed' })

  const entries = day.dayQuery.data?.entries ?? []
  const dayData = day.dayQuery.data
  const clocking = useClocking()
  const summary = day.dayQuery.data?.summary
  const week = day.dayQuery.data?.week
  const { timed, untimed } = splitDayEntries(entries)
  const jobCount = distinctJobCount(entries)

  const openEdit = (entryId: string) => {
    const entry = entries.find((candidate) => candidate.id === entryId)
    if (entry) setDrawer({ mode: 'edit', entry })
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-gray-900">Workshop timesheets</h1>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <Button
            variant="outline"
            size="icon"
            className={TOUCH_TARGET_CLASS}
            aria-label="Previous day"
            data-automation-id="WorkshopMyTimeHeader-previous-day"
            onClick={() => onDateChange(shiftDate(date, -1))}
          >
            <ChevronLeft />
          </Button>
          <span
            className="min-w-0 flex-1 text-center text-sm font-medium text-gray-700 sm:min-w-56 sm:flex-none"
            data-automation-id="WorkshopMyTimeHeader-date"
          >
            {formatDateLong(date)}
          </span>
          <Button
            variant="outline"
            size="icon"
            className={TOUCH_TARGET_CLASS}
            aria-label="Next day"
            data-automation-id="WorkshopMyTimeHeader-next-day"
            onClick={() => onDateChange(shiftDate(date, 1))}
          >
            <ChevronRight />
          </Button>
        </div>
      </div>

      {dayData !== undefined && (
        <DayCard
          // A fresh card per day: an open times form belongs to the day it was opened on.
          key={date}
          date={date}
          isToday={date === localIsoDate()}
          day={dayData.day}
          pending={dayData.pending}
          dayStart={workingDayStart(date, companyDefaults)}
          clocking={clocking.clocking}
          onClock={clocking.clock}
          onSetTimes={(clockIn, clockOut) =>
            clocking.setTimes({ date, clock_in: clockIn, clock_out: clockOut })
          }
          onOpenDay={onDateChange}
        />
      )}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <SummaryCard label="Total" valueAutomationId="WorkshopTimesheetSummaryCard-total-hours">
            {formatHoursDisplay(summary?.total_hours)}
          </SummaryCard>
          <SummaryCard
            label="Billable"
            valueAutomationId="WorkshopTimesheetSummaryCard-billable-hours"
          >
            {formatHoursDisplay(summary?.billable_hours)}
          </SummaryCard>
          <SummaryCard
            label="Non-billable"
            valueAutomationId="WorkshopTimesheetSummaryCard-non-billable-hours"
          >
            {formatHoursDisplay(summary?.non_billable_hours)}
          </SummaryCard>
          {/* The week payroll pays by: approved hours are paid, waiting hours
              are not until the office approves them. */}
          <SummaryCard
            label="Approved this week"
            valueAutomationId="WorkshopTimesheetSummaryCard-week-approved-hours"
          >
            {formatHoursDisplay(week?.approved_hours)}
          </SummaryCard>
          <SummaryCard
            label="Waiting this week"
            valueAutomationId="WorkshopTimesheetSummaryCard-week-waiting-hours"
          >
            {formatHoursDisplay(week?.waiting_hours)}
          </SummaryCard>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="text-sm text-gray-600"
            data-automation-id="WorkshopTimesheetSummaryCard-job-count"
          >
            {jobCount === 1 ? '1 job' : `${jobCount} jobs`}
          </span>
          <Button
            variant="outline"
            className={TOUCH_TARGET_CLASS}
            aria-label="Refresh"
            data-automation-id="WorkshopTimesheetSummaryCard-refresh"
            disabled={day.dayQuery.isFetching}
            onClick={day.refetch}
          >
            <RefreshCw /> Refresh
          </Button>
          <Button
            className={TOUCH_TARGET_CLASS}
            data-automation-id="WorkshopTimesheetSummaryCard-add"
            onClick={() => setDrawer({ mode: 'create', start: null })}
          >
            <Plus /> Add entry
          </Button>
        </div>
      </div>

      <QueryState
        isPending={day.dayQuery.isPending}
        isError={day.dayQuery.isError}
        onRetry={() => void day.dayQuery.refetch()}
        loadingLabel="Loading your timesheet entries..."
        errorLabel="Failed to load your timesheet entries."
      >
        {entries.length === 0 && (
          <p
            className="text-center text-sm text-gray-500"
            data-automation-id="WorkshopMyTimePage-empty-hint"
          >
            No entries yet. Tap the calendar to add the first block.
          </p>
        )}
        <WorkshopTimesheetCalendar
          date={date}
          events={timed.map(calendarEvent)}
          onEventClick={openEdit}
          onSlotClick={(start) => setDrawer({ mode: 'create', start })}
        />
        {untimed.length > 0 && (
          <UntimedEntries
            entries={untimed}
            isLocked={(entry) => entryLockedFor(entry, user)}
            deleting={day.saving}
            onEdit={openEdit}
            onDelete={(entryId) => void day.deleteEntry(entryId)}
          />
        )}
      </QueryState>

      <WorkshopTimesheetEntryDrawer
        state={drawer}
        locked={drawer.mode === 'edit' && entryLockedFor(drawer.entry, user)}
        date={date}
        dayEntries={entries}
        dayStart={workingDayStart(date, companyDefaults)}
        saving={day.saving}
        onCreate={day.createEntry}
        onUpdate={day.updateEntry}
        onDelete={day.deleteEntry}
        onClose={() => setDrawer({ mode: 'closed' })}
      />
    </div>
  )
}

/**
 * Entries the calendar cannot place, as a table: each row says what was
 * booked, at what rate and whether it bills, and can be edited (to add the
 * missing times) or deleted where it stands.
 */
function UntimedEntries({
  entries,
  isLocked,
  deleting,
  onEdit,
  onDelete,
}: {
  entries: WorkshopTimesheetEntryOut[]
  isLocked: (entry: WorkshopTimesheetEntryOut) => boolean
  deleting: boolean
  onEdit: (entryId: string) => void
  onDelete: (entryId: string) => void
}) {
  return (
    <div
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      data-automation-id="WorkshopMyTimePage-untimed"
    >
      <h2 className="mb-2 text-sm font-semibold text-gray-700">Entries without times</h2>
      <ul className="divide-y divide-gray-100">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="flex items-center justify-between gap-3 py-2 text-sm"
            data-event-id={entry.id}
          >
            <div className="min-w-0">
              <div className="truncate font-medium text-gray-900">
                #{entry.job_number} {entry.job_name}
              </div>
              {entry.company_name !== '' && (
                <div className="truncate text-xs text-gray-500">{entry.company_name}</div>
              )}
              {entry.description !== '' && (
                <div className="truncate text-gray-600">{entry.description}</div>
              )}
              <div className="mt-1 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-slate-100 px-2 py-0.5">
                  {rateLabel(entry.wage_rate_multiplier)}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 font-semibold ${entry.is_billable ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-200 text-gray-600'}`}
                >
                  {entry.is_billable ? 'Billable' : 'Non-billable'}
                </span>
                {entryMarks(entry).map((mark) => (
                  <span
                    key={mark}
                    className="rounded-full bg-slate-100 px-2 py-0.5 font-semibold text-slate-700"
                    data-automation-id={`WorkshopMyTimePage-untimed-mark-${entry.id}`}
                  >
                    {mark}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="font-medium">{formatHoursDisplay(entry.hours)}</span>
              <Button
                variant="outline"
                size="icon"
                className={TOUCH_TARGET_CLASS}
                aria-label="Edit entry"
                data-automation-id={`WorkshopMyTimePage-untimed-edit-${entry.id}`}
                onClick={() => onEdit(entry.id)}
              >
                <Pencil />
              </Button>
              <Button
                variant="outline"
                size="icon"
                className={TOUCH_TARGET_CLASS}
                aria-label="Delete entry"
                disabled={deleting || isLocked(entry)}
                data-automation-id={`WorkshopMyTimePage-untimed-delete-${entry.id}`}
                onClick={() => onDelete(entry.id)}
              >
                <Trash2 />
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
