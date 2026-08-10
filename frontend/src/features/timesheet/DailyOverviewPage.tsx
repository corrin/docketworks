import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ChevronLeft, ChevronRight, Loader2, RefreshCw } from 'lucide-react'

import { getDailyTimesheetSummaryByDateOptions } from '@/api'
import type { DailyTimesheetSummaryOut } from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'
import { formatDate, localIsoDate } from '@/lib/format'
import { shiftDate } from '@/lib/dates'

export interface DailyOverviewSearch {
  date?: string
}

export interface DailyOverviewPageProps {
  search: DailyOverviewSearch
  onDateChange: (date: string) => void
  onOpenEntry: (staffId: string, date: string) => void
}

type StaffDaily = DailyTimesheetSummaryOut['staff_data'][number]

/**
 * The read-only daily overview: every staff member's day at a glance. Date
 * navigation is a plain ±1 day (v1's daily page never skips weekends — the
 * weekend rule belongs to the ENTRY page's navigation).
 */
export function DailyOverviewPage({ search, onDateChange, onOpenEntry }: DailyOverviewPageProps) {
  const date = search.date ?? localIsoDate()
  const queryClient = useQueryClient()
  const summaryQuery = useQuery(
    getDailyTimesheetSummaryByDateOptions({ path: { target_date: date } }),
  )

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-4 text-lg font-semibold text-slate-800">Daily Timesheets</h1>
        <Button
          variant="outline"
          size="sm"
          aria-label="Previous day"
          onClick={() => onDateChange(shiftDate(date, -1))}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <input
          type="date"
          value={date}
          aria-label="Date"
          className="rounded border border-slate-200 px-2 py-1 text-sm"
          onChange={(event) => {
            if (event.target.value) onDateChange(event.target.value)
          }}
        />
        <Button
          variant="outline"
          size="sm"
          aria-label="Next day"
          onClick={() => onDateChange(shiftDate(date, 1))}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" onClick={() => onDateChange(localIsoDate())}>
          Today
        </Button>
        <span className="text-sm text-slate-600">{formatDate(date)}</span>
        <Button
          variant="outline"
          size="sm"
          aria-label="Refresh"
          onClick={() =>
            void queryClient.invalidateQueries({
              queryKey: getDailyTimesheetSummaryByDateOptions({ path: { target_date: date } })
                .queryKey,
            })
          }
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <QueryState
        isPending={summaryQuery.isPending}
        isError={summaryQuery.isError && summaryQuery.data === undefined}
        loadingNode={
          <div className="flex items-center justify-center py-24">
            <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
          </div>
        }
        errorNode={
          <p className="text-sm font-medium text-red-700">
            Could not load the daily summary. Reload the page.
          </p>
        }
      >
        {summaryQuery.data && (
          <table className="min-w-full table-fixed text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-600">
                <th className="w-64 px-2 py-2">Staff Member</th>
                <th className="w-24 px-2 py-2">Hours</th>
                <th className="w-28 px-2 py-2">Status</th>
                <th className="w-32 px-2 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {summaryQuery.data.staff_data.map((staff) => (
                <StaffRow
                  key={staff.staff_id}
                  staff={staff}
                  onOpen={() => onOpenEntry(staff.staff_id, date)}
                />
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
      {/* SEAM: v1's StaffDetailModal and MetricsModal render data already in
          this summary payload; both are deferred — no spec asserts them. */}
    </div>
  )
}

function StaffRow({ staff, onOpen }: { staff: StaffDaily; onOpen: () => void }) {
  const completion = Math.max(0, Math.min(100, staff.completion_percentage))
  return (
    <tr
      className="border-b border-slate-100 hover:bg-slate-50"
      data-automation-id={`StaffRow-row-${staff.staff_id}`}
    >
      <td className="px-2 py-2">
        <button
          type="button"
          className="flex cursor-pointer items-center gap-2 text-left"
          data-automation-id={`StaffRow-name-${staff.staff_id}`}
          onClick={onOpen}
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700">
            {staff.staff_initials}
          </span>
          <span className="font-medium text-slate-800">{staff.staff_name}</span>
          <span className="text-xs text-slate-500">
            {staff.entry_count} {staff.entry_count === 1 ? 'entry' : 'entries'}
          </span>
        </button>
      </td>
      <td className="px-2 py-2">
        <div className="text-slate-700">
          {staff.actual_hours} / {staff.scheduled_hours}h
        </div>
        <div className="mt-1 h-1.5 w-20 overflow-hidden rounded bg-slate-200">
          <div className="h-full bg-emerald-500" style={{ width: `${completion}%` }} />
        </div>
      </td>
      <td className="px-2 py-2">
        {staff.status === 'No Entry' ? (
          <span
            className="inline-flex items-center gap-1 text-red-600"
            title={staff.alerts.join('; ')}
          >
            <AlertTriangle className="h-4 w-4" />
            {staff.status}
          </span>
        ) : (
          <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
            {staff.status}
          </span>
        )}
      </td>
      <td className="px-2 py-2">
        <Button variant="outline" size="sm" onClick={onOpen}>
          Edit Timesheet
        </Button>
      </td>
    </tr>
  )
}
