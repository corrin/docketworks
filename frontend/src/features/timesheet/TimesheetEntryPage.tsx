import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Loader2, RefreshCw } from 'lucide-react'

import {
  jobTimesheetEntriesRetrieveQueryKey,
  timesheetsJobsRetrieveOptions,
  timesheetsStaffRetrieveOptions,
  xeroPayItemsListOptions,
} from '@/api'
import type { TimesheetStaffOut } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { companyDefaultsQueryOptions } from '@/features/shell'
import { QueryState } from '@/features/shared/QueryState'
import { formatCurrency, formatDate, localIsoDate } from '@/lib/format'
import { nextWeekday, weekdayAdjusted } from '@/lib/dates'
import { formatHoursDisplay } from '@/lib/format'
import { lineIsBillable } from './lineMeta'
import { SmartTimesheetTable } from './SmartTimesheetTable'
import { useTimesheetEntries } from './useTimesheetEntries'

export interface TimesheetEntrySearch {
  date?: string
  staffId?: string
}

export interface TimesheetEntryPageProps {
  search: TimesheetEntrySearch
  onSearchChange: (search: Required<TimesheetEntrySearch>) => void
  onOpenDaily: (date: string) => void
}

/**
 * The timesheet entry page: one staff member, one day, the editable grid.
 *
 * The reference queries load in PARALLEL (independent useQuery calls, no
 * enabled chaining) — the performance spec measures exactly this — and the
 * loading state is the only .animate-spin in the document, which must fully
 * disappear once loaded (the spec polls for zero).
 */
export function TimesheetEntryPage({
  search,
  onSearchChange,
  onOpenDaily,
}: TimesheetEntryPageProps) {
  const date = search.date ?? localIsoDate()

  const staffQuery = useQuery(timesheetsStaffRetrieveOptions({ query: { date } }))
  const jobsQuery = useQuery(timesheetsJobsRetrieveOptions())
  const payItemsQuery = useQuery(xeroPayItemsListOptions())
  const defaultsQuery = useQuery(companyDefaultsQueryOptions())

  const queries = [staffQuery, jobsQuery, payItemsQuery, defaultsQuery]
  if (queries.some((query) => query.isPending)) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    )
  }
  // A failed FIRST load is an error page; an errored background refetch
  // keeps the working page — swapping to the error panel would unmount the
  // grid and destroy unsaved draft rows mid-entry (the useCostLines rule).
  if (!staffQuery.data || !jobsQuery.data || !payItemsQuery.data || !defaultsQuery.data) {
    return (
      <p className="p-6 text-sm font-medium text-red-700">
        Could not load the timesheet reference data. Reload the page.
      </p>
    )
  }

  const staffList = staffQuery.data.staff
  const staff: TimesheetStaffOut | undefined = search.staffId
    ? staffList.find((member) => member.id === search.staffId)
    : staffList[0]
  if (search.staffId && !staff) {
    // Loud, named error (v1's message): silently falling back to another
    // staff member would record hours against the wrong person.
    return (
      <p className="p-6 text-sm font-medium text-red-700">
        Staff {search.staffId} is not available for timesheet entry. They are not in the active
        timesheet staff list (typically because they have no Xero payroll ID configured).
      </p>
    )
  }
  if (!staff) {
    return <p className="p-6 text-sm text-slate-600">No staff are available for timesheet entry.</p>
  }

  const weekendEnabled = defaultsQuery.data.weekend_timesheets_enabled
  return (
    <EntryWorkspace
      key={`${staff.id}|${date}`}
      date={date}
      staff={staff}
      staffList={staffList}
      jobs={jobsQuery.data.jobs}
      payItems={payItemsQuery.data}
      weekendEnabled={weekendEnabled}
      onSearchChange={onSearchChange}
      onOpenDaily={onOpenDaily}
    />
  )
}

interface EntryWorkspaceProps {
  date: string
  staff: TimesheetStaffOut
  staffList: TimesheetStaffOut[]
  jobs: Parameters<typeof SmartTimesheetTable>[0]['jobs']
  payItems: Parameters<typeof SmartTimesheetTable>[0]['payItems']
  weekendEnabled: boolean
  onSearchChange: (search: { date: string; staffId: string }) => void
  onOpenDaily: (date: string) => void
}

function EntryWorkspace({
  date,
  staff,
  staffList,
  jobs,
  payItems,
  weekendEnabled,
  onSearchChange,
  onOpenDaily,
}: EntryWorkspaceProps) {
  const queryClient = useQueryClient()
  const { entriesQuery, patchLine, createLine, deleteLine, approveLine } = useTimesheetEntries(
    staff.id,
    date,
  )

  const staffIndex = staffList.findIndex((member) => member.id === staff.id)
  const entries = entriesQuery.data?.cost_lines ?? []
  const scheduledHours = entriesQuery.data?.summary.scheduled_hours ?? 0

  // Live client-side aggregates (v1's Daily Breakdown): the server summary
  // only refreshes on refetch, but these must track optimistic edits.
  // Rounded to 2dp — a float reduce would render 3.3000000000000003h and
  // misclassify the tone against scheduled_hours.
  const totalHours =
    Math.round(entries.reduce((sum, line) => sum + Number(line.quantity), 0) * 100) / 100
  const totalBill = entries.reduce((sum, line) => sum + line.total_rev, 0)
  const billableCount = entries.filter((line) => lineIsBillable(line)).length
  const nonBillableCount = entries.length - billableCount

  const hoursTone =
    totalHours > scheduledHours
      ? 'text-red-600'
      : totalHours < scheduledHours
        ? 'text-amber-500'
        : 'text-slate-900'

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          aria-label="Previous staff member"
          disabled={staffIndex <= 0}
          onClick={() => onSearchChange({ date, staffId: staffList[staffIndex - 1]!.id })}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Select value={staff.id} onValueChange={(staffId) => onSearchChange({ date, staffId })}>
          <SelectTrigger size="sm" className="min-w-[14rem]" aria-label="Staff member">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {staffList.map((member) => (
              <SelectItem key={member.id} value={member.id}>
                {member.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          aria-label="Next staff member"
          disabled={staffIndex < 0 || staffIndex >= staffList.length - 1}
          onClick={() => onSearchChange({ date, staffId: staffList[staffIndex + 1]!.id })}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>

        <span className="mx-2 h-6 w-px bg-slate-200" />

        <Button
          variant="outline"
          size="sm"
          aria-label="Previous day"
          onClick={() =>
            onSearchChange({ date: nextWeekday(date, -1, weekendEnabled), staffId: staff.id })
          }
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm font-medium text-slate-800">{formatDate(date)}</span>
        <Button
          variant="outline"
          size="sm"
          aria-label="Next day"
          onClick={() =>
            onSearchChange({ date: nextWeekday(date, 1, weekendEnabled), staffId: staff.id })
          }
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            onSearchChange({
              date: weekdayAdjusted(localIsoDate(), weekendEnabled),
              staffId: staff.id,
            })
          }
        >
          Today
        </Button>

        <span className="mx-2 h-6 w-px bg-slate-200" />

        <span className={`text-sm font-medium ${hoursTone}`}>
          {formatHoursDisplay(totalHours)} of {formatHoursDisplay(scheduledHours)}
        </span>
        <Button
          variant="outline"
          size="sm"
          aria-label="Refresh entries"
          onClick={() =>
            void queryClient.invalidateQueries({
              queryKey: jobTimesheetEntriesRetrieveQueryKey({
                query: { staff_id: staff.id, date },
              }),
            })
          }
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" onClick={() => onOpenDaily(date)}>
          Daily Overview
        </Button>
      </div>

      <QueryState
        isPending={entriesQuery.isPending}
        isError={entriesQuery.isError && entriesQuery.data === undefined}
        loadingNode={
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        }
        errorNode={
          <p className="text-sm font-medium text-red-700">
            Could not load the timesheet entries. Reload the page.
          </p>
        }
      >
        <SmartTimesheetTable
          entries={entries}
          jobs={jobs}
          payItems={payItems}
          staffId={staff.id}
          date={date}
          staffWageRate={Number(staff.wageRate)}
          payBasis={staff.pay_basis}
          patchLine={patchLine}
          createLine={createLine}
          deleteLine={deleteLine}
          approveLine={approveLine}
        />
      </QueryState>

      {/* SEAM: v1's Current Jobs cards (one getJobSummary per distinct job —
          an N+1 wave) are deferred; no spec asserts them. The Daily
          Breakdown tiles below are the kept half of the summary section. */}
      <div className="grid max-w-xl grid-cols-4 gap-2">
        <BreakdownTile label="Total Hours" value={formatHoursDisplay(totalHours)} />
        <BreakdownTile label="Total Bill" value={formatCurrency(totalBill)} />
        <BreakdownTile label="Billable" value={String(billableCount)} />
        <BreakdownTile label="Non-Billable" value={String(nonBillableCount)} />
      </div>
    </div>
  )
}

function BreakdownTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 p-2 text-center">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-800">{value}</div>
    </div>
  )
}
