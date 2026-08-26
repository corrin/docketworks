import { ChevronLeft, ChevronRight, Plus, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import type { WorkshopTimesheetEntryOut } from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'
import { SummaryCard } from '@/features/shared/SummaryCard'
import { formatDateLong, localIsoDate } from '@/lib/format'
import { shiftDate } from '@/lib/dates'

import { formatHoursDisplay } from './hours'
import { calendarEvent, splitDayEntries } from './myTime'
import { useWorkshopDay } from './useWorkshopDay'
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
  const day = useWorkshopDay(date)
  const [drawer, setDrawer] = useState<EntryDrawerState>({ mode: 'closed' })

  const entries = day.dayQuery.data?.entries ?? []
  const summary = day.dayQuery.data?.summary
  const { timed, untimed } = splitDayEntries(entries)

  const openEdit = (entryId: string) => {
    const entry = entries.find((candidate) => candidate.id === entryId)
    if (entry) setDrawer({ mode: 'edit', entry })
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-gray-900">Workshop timesheets</h1>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            aria-label="Previous day"
            data-automation-id="WorkshopMyTimeHeader-previous-day"
            onClick={() => onDateChange(shiftDate(date, -1))}
          >
            <ChevronLeft />
          </Button>
          <span
            className="min-w-56 text-center text-sm font-medium text-gray-700"
            data-automation-id="WorkshopMyTimeHeader-date"
          >
            {formatDateLong(date)}
          </span>
          <Button
            variant="outline"
            size="icon"
            aria-label="Next day"
            data-automation-id="WorkshopMyTimeHeader-next-day"
            onClick={() => onDateChange(shiftDate(date, 1))}
          >
            <ChevronRight />
          </Button>
        </div>
      </div>

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
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            aria-label="Refresh"
            data-automation-id="WorkshopTimesheetSummaryCard-refresh"
            onClick={day.refetch}
          >
            <RefreshCw /> Refresh
          </Button>
          <Button
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
        <WorkshopTimesheetCalendar
          date={date}
          events={timed.map(calendarEvent)}
          onEventClick={openEdit}
          onSlotClick={(start) => setDrawer({ mode: 'create', start })}
        />
        {untimed.length > 0 && <UntimedEntries entries={untimed} onEdit={openEdit} />}
      </QueryState>

      <WorkshopTimesheetEntryDrawer
        state={drawer}
        date={date}
        saving={day.saving}
        onCreate={day.createEntry}
        onUpdate={day.updateEntry}
        onDelete={day.deleteEntry}
        onClose={() => setDrawer({ mode: 'closed' })}
      />
    </div>
  )
}

function UntimedEntries({
  entries,
  onEdit,
}: {
  entries: WorkshopTimesheetEntryOut[]
  onEdit: (entryId: string) => void
}) {
  return (
    <div
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      data-automation-id="WorkshopMyTimePage-untimed"
    >
      <h2 className="mb-2 text-sm font-semibold text-gray-700">Entries without times</h2>
      <ul className="divide-y divide-gray-100">
        {entries.map((entry) => (
          <li key={entry.id}>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 py-2 text-left text-sm hover:bg-slate-50"
              data-event-id={entry.id}
              onClick={() => onEdit(entry.id)}
            >
              <span className="truncate">
                #{entry.job_number} {entry.job_name}
                {entry.description !== '' && (
                  <span className="text-gray-500"> — {entry.description}</span>
                )}
              </span>
              <span className="shrink-0 font-medium">{formatHoursDisplay(entry.hours)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
