import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronLeft, ChevronRight, Loader2, RefreshCw } from 'lucide-react'

import { timesheetsWeeklyRetrieveOptions, timesheetsWeeklyRetrieveQueryKey } from '@/api'
import type { WeeklyStaffDataOut, WeeklyTimesheetDataOut } from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'
import { formatCurrency, formatDate, localIsoDate } from '@/lib/format'
import { isIsoDateString, mondayOf, shiftDate } from '@/lib/dates'

import { PayrollPanel } from './PayrollPanel'
import { usePayrollWeek } from './usePayrollWeek'

const DAYS_IN_WEEK = 7

/**
 * Read `?week=` as the payroll week it belongs to.
 *
 * Opus: Snapped to its Monday, not merely validated as a date: a payroll week IS a
 * Monday — `_WeekWindow.of` refuses anything else server-side — so a valid but
 * mid-week value ran the grid, the displayed range and the whole payroll panel
 * off a Tuesday, presenting a week that could never be posted as if it could.
 */
export function weeklySearchFromUrl(search: Record<string, unknown>): WeeklyOverviewSearch {
  return {
    week:
      typeof search.week === 'string' && isIsoDateString(search.week)
        ? mondayOf(search.week)
        : undefined,
  }
}

export interface WeeklyOverviewSearch {
  week?: string
}

export interface WeeklyOverviewPageProps {
  search: WeeklyOverviewSearch
  onWeekChange: (week: string) => void
  onOpenDay: (date: string) => void
  onOpenEntry: (staffId: string, date: string) => void
}

/**
 * The weekly overview: staff down the side, days across the top, with the
 * week's payroll posted from the same screen.
 *
 * Opus: A cell is one staff member's day, and it carries the same day_status the
 * daily overview shows for that day — the two screens are the same question at
 * two zoom levels, so clicking a day header opens that day and clicking a cell
 * opens that person's entries for it.
 */
export function WeeklyOverviewPage({
  search,
  onWeekChange,
  onOpenDay,
  onOpenEntry,
}: WeeklyOverviewPageProps) {
  const weekStart = search.week ?? mondayOf(localIsoDate())
  const queryClient = useQueryClient()
  const weekQuery = useQuery(timesheetsWeeklyRetrieveOptions({ query: { start_date: weekStart } }))
  const payroll = usePayrollWeek(weekStart)

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-4 text-lg font-semibold text-slate-800">Weekly Timesheets</h1>
        <Button
          variant="outline"
          size="sm"
          aria-label="Previous week"
          onClick={() => onWeekChange(shiftDate(weekStart, -DAYS_IN_WEEK))}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <input
          type="date"
          value={weekStart}
          aria-label="Week starting"
          className="rounded border border-slate-200 px-2 py-1 text-sm"
          onChange={(event) => {
            // Opus: Any day picked selects the week it falls in; pay periods are
            // Monday-anchored, so a mid-week date is not a different week.
            if (event.target.value) onWeekChange(mondayOf(event.target.value))
          }}
        />
        <Button
          variant="outline"
          size="sm"
          aria-label="Next week"
          onClick={() => onWeekChange(shiftDate(weekStart, DAYS_IN_WEEK))}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" onClick={() => onWeekChange(mondayOf(localIsoDate()))}>
          This week
        </Button>
        <span className="text-sm text-slate-600" data-automation-id="WeeklyOverview-range">
          {formatDate(weekStart)} – {formatDate(shiftDate(weekStart, DAYS_IN_WEEK - 1))}
        </span>
        <Button
          variant="outline"
          size="sm"
          aria-label="Refresh"
          onClick={() =>
            void queryClient.invalidateQueries({
              queryKey: timesheetsWeeklyRetrieveQueryKey({ query: { start_date: weekStart } }),
            })
          }
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <PayrollPanel
        weekStart={weekStart}
        payroll={payroll}
        staffIds={(weekQuery.data?.staff_data ?? []).map((staff) => staff.staff_id)}
      />

      <QueryState
        isPending={weekQuery.isPending}
        isError={weekQuery.isError && weekQuery.data === undefined}
        loadingNode={
          <div className="flex items-center justify-center py-24">
            <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
          </div>
        }
        errorNode={
          <p className="text-sm font-medium text-red-700">
            Could not load the weekly summary. Reload the page.
          </p>
        }
      >
        {weekQuery.data && (
          <WeekTable week={weekQuery.data} onOpenDay={onOpenDay} onOpenEntry={onOpenEntry} />
        )}
      </QueryState>
    </div>
  )
}

function WeekTable({
  week,
  onOpenDay,
  onOpenEntry,
}: {
  week: WeeklyTimesheetDataOut
  onOpenDay: (date: string) => void
  onOpenEntry: (staffId: string, date: string) => void
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm" data-automation-id="WeeklyOverview-table">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-600">
            <th className="w-56 px-2 py-2">Staff Member</th>
            {week.week_days.map((day) => (
              <th key={day} className="w-24 px-2 py-2">
                <button
                  type="button"
                  className="cursor-pointer text-left hover:underline"
                  data-automation-id={`WeeklyOverview-dayHeader-${day}`}
                  onClick={() => onOpenDay(day)}
                >
                  {formatDate(day)}
                </button>
              </th>
            ))}
            <th className="w-24 px-2 py-2">Total</th>
            <th className="w-24 px-2 py-2">Billable</th>
            <th className="w-28 px-2 py-2">Cost</th>
          </tr>
        </thead>
        <tbody>
          {week.staff_data.map((staff) => (
            <StaffWeekRow key={staff.staff_id} staff={staff} onOpenEntry={onOpenEntry} />
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-slate-300 bg-slate-50 font-semibold text-slate-800">
            {/* Totals come from the server's weekly_summary, never recomputed
                here — v1 shipped both and showed the client's. */}
            <td className="px-2 py-2">{week.weekly_summary.staff_count} staff</td>
            <td className="px-2 py-2" colSpan={week.week_days.length} />
            <td className="px-2 py-2" data-automation-id="WeeklyOverview-totalHours">
              {week.weekly_summary.total_hours}h
            </td>
            <td className="px-2 py-2">{week.weekly_summary.billable_percentage ?? 0}%</td>
            <td className="px-2 py-2" />
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

/** The tone each day-status word carries, shared with the daily overview's vocabulary. */
const DAY_STATUS_TONE: Record<string, string> = {
  Complete: 'bg-emerald-50 text-emerald-800',
  Partial: 'bg-amber-50 text-amber-800',
  'No Entry': 'bg-red-50 text-red-800',
  Leave: 'bg-sky-50 text-sky-800',
  Unscheduled: 'bg-sky-50 text-sky-800',
  Off: 'bg-slate-50 text-slate-500',
}

function StaffWeekRow({
  staff,
  onOpenEntry,
}: {
  staff: WeeklyStaffDataOut
  onOpenEntry: (staffId: string, date: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <tr
        className="border-b border-slate-100 hover:bg-slate-50"
        data-automation-id={`WeeklyOverview-row-${staff.staff_id}`}
      >
        <td className="px-2 py-2">
          <button
            type="button"
            className="flex cursor-pointer items-center gap-1 text-left font-medium text-slate-800"
            aria-expanded={expanded}
            data-automation-id={`WeeklyOverview-expand-${staff.staff_id}`}
            onClick={() => setExpanded((open) => !open)}
          >
            <ChevronDown
              className={`h-4 w-4 transition-transform ${expanded ? '' : '-rotate-90'}`}
            />
            {staff.staff_name}
          </button>
          <span className="ml-5 text-xs text-slate-500">{staff.week_status}</span>
          {staff.pay_basis === 'salary' && (
            <span className="ml-2 rounded bg-violet-50 px-1.5 py-0.5 text-xs font-medium text-violet-700">
              Salary
            </span>
          )}
          {/* The server already quantizes variance_hours to 0.01, so zero is
              the only "no variance" value — a client-side band on top of that
              was a second materiality rule, and it swallowed a genuine 0.01h. */}
          {staff.pay_basis === 'salary' && staff.variance_hours !== 0 && (
            <span className="ml-2 text-xs text-amber-700">
              {staff.variance_hours < 0
                ? `${Math.abs(staff.variance_hours)}h unallocated`
                : `${staff.variance_hours}h over expected`}{' '}
              — salary unchanged
            </span>
          )}
        </td>
        {staff.weekly_hours.map((day) => (
          <td key={day.day} className="px-2 py-2">
            <button
              type="button"
              className={`w-full cursor-pointer rounded px-1 py-0.5 text-left ${
                DAY_STATUS_TONE[day.day_status] ?? 'bg-slate-50 text-slate-700'
              }`}
              title={day.day_status}
              data-automation-id={`WeeklyOverview-cell-${staff.staff_id}-${day.day}`}
              onClick={() => onOpenEntry(staff.staff_id, day.day)}
            >
              {day.hours > 0 ? `${day.hours}h` : day.day_status}
            </button>
          </td>
        ))}
        <td className="px-2 py-2" data-automation-id={`WeeklyOverview-total-${staff.staff_id}`}>
          {staff.total_hours}h
        </td>
        <td className="px-2 py-2">{staff.billable_percentage}%</td>
        <td className="px-2 py-2">{formatCurrency(staff.weekly_cost)}</td>
      </tr>
      {expanded && <PayrollBreakdownRows staff={staff} />}
    </>
  )
}

/** The payroll categories behind a staff member's week, one row each. */
const BREAKDOWN_ROWS = [
  { label: 'Billed', day: 'billed_hours', total: 'total_billed_hours' },
  { label: 'Unbilled', day: 'unbilled_hours', total: 'total_unbilled_hours' },
  { label: 'Overtime 1.5x', day: 'overtime_1_5x_hours', total: 'total_overtime_1_5x_hours' },
  { label: 'Overtime 2x', day: 'overtime_2x_hours', total: 'total_overtime_2x_hours' },
  { label: 'Sick leave', day: 'sick_leave_hours', total: 'total_sick_leave_hours' },
  { label: 'Annual leave', day: 'annual_leave_hours', total: 'total_annual_leave_hours' },
  {
    label: 'Bereavement leave',
    day: 'bereavement_leave_hours',
    total: 'total_bereavement_leave_hours',
  },
  { label: 'Other leave', day: 'other_leave_hours', total: 'total_other_leave_hours' },
] as const

function PayrollBreakdownRows({ staff }: { staff: WeeklyStaffDataOut }) {
  return (
    <>
      {BREAKDOWN_ROWS.filter((row) => staff[row.total] > 0).map((row) => (
        <tr
          key={row.label}
          className="border-b border-slate-100 bg-slate-50/60 text-xs text-slate-600"
          data-automation-id={`WeeklyOverview-breakdown-${staff.staff_id}-${row.label}`}
        >
          <td className="px-2 py-1 pl-9">{row.label}</td>
          {staff.weekly_hours.map((day) => (
            <td key={day.day} className="px-2 py-1">
              {day[row.day] > 0 ? `${day[row.day]}h` : ''}
            </td>
          ))}
          <td className="px-2 py-1">{staff[row.total]}h</td>
          <td className="px-2 py-1" />
          <td className="px-2 py-1" />
        </tr>
      ))}
    </>
  )
}
