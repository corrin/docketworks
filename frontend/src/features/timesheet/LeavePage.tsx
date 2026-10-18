import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import {
  apiErrorMessage,
  timesheetsLeaveRequestsDeleteMutation,
  timesheetsLeaveRequestsListOptions,
  timesheetsLeaveRequestsListQueryKey,
  timesheetsLeaveSettingsRetrieveOptions,
  timesheetsStaffRetrieveOptions,
  type LeaveRequestOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'
import { SummaryCard } from '@/features/shared/SummaryCard'
import { formatDate, localIsoDate } from '@/lib/format'

import { LeaveRequestDialog } from './LeaveRequestDialog'
import { OfficeClosureDialog } from './OfficeClosureDialog'
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from '@/features/shared/useDebouncedValue'
import { SearchInput } from '@/features/shared/SearchInput'
import { TabBar, type TabBarItem } from '@/features/shared/TabBar'

export type LeaveScope = 'current' | 'history'

export function LeavePage() {
  const { t } = useTranslation('timesheet')
  // Opus: Explicit labels rather than the CSS `capitalize` the pill tabs used —
  // the shared bar renders a label string, and every other tab bar in the app
  // already names its tabs rather than styling its keys into titles.
  const leaveTabs: readonly TabBarItem<LeaveScope>[] = [
    { key: 'current', label: t('leave.currentTab') },
    { key: 'history', label: t('leave.historyTab') },
  ]
  const [scope, setScope] = useState<LeaveScope>('current')
  const [search, setSearch] = useState('')
  const [newOpen, setNewOpen] = useState(false)
  const [closureOpen, setClosureOpen] = useState(false)
  const [editing, setEditing] = useState<LeaveRequestOut | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  // Opus: Debounced, like every other search box on the app: the raw value drives the
  // input and the settled one drives the request, or every keystroke is a query.
  const debouncedSearch = useDebouncedValue(search, SEARCH_DEBOUNCE_MS)
  const listQuery = useQuery(
    timesheetsLeaveRequestsListOptions({ query: { scope, search: debouncedSearch } }),
  )
  const settingsQuery = useQuery(timesheetsLeaveSettingsRetrieveOptions())
  const staffQuery = useQuery(timesheetsStaffRetrieveOptions({ query: { date: localIsoDate() } }))
  const settingsError = settingsQuery.isError
  const staffError = staffQuery.isError
  const deleteMutation = useMutation(timesheetsLeaveRequestsDeleteMutation())

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: timesheetsLeaveRequestsListQueryKey() })
  }

  const configuredTypes = useMemo(
    () => settingsQuery.data?.leave_types.filter((type) => type.configured) ?? [],
    [settingsQuery.data],
  )

  const cancelRequest = async (request: LeaveRequestOut) => {
    if (
      !window.confirm(
        t('leave.confirmCancel', {
          leaveType: request.leave_type_name,
          staffName: request.staff_name,
        }),
      )
    )
      return
    setActionError(null)
    try {
      await deleteMutation.mutateAsync({ path: { request_id: request.id } })
      await refresh()
    } catch (error) {
      setActionError(apiErrorMessage(error, t('leave.cancelFailed')))
    }
  }

  return (
    <main className="space-y-5 p-5" data-automation-id="LeavePage-root">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">{t('leave.title')}</h1>
          <p className="text-sm text-slate-500">{t('leave.subtitle')}</p>
        </div>
        <div className="flex flex-col gap-2">
          {(staffError || settingsError) && (
            <p className="text-xs text-red-700">
              {staffError && t('leave.staffLoadFailed')}
              {settingsError && t('leave.settingsLoadFailed')}
              <button
                type="button"
                className="underline"
                onClick={() => {
                  if (staffError) void staffQuery.refetch()
                  if (settingsError) void settingsQuery.refetch()
                }}
              >
                {t('leave.retry')}
              </button>
            </p>
          )}
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setClosureOpen(true)}>
              <CalendarDays className="h-4 w-4" /> {t('leave.officeClosed')}
            </Button>
            <Button data-automation-id="LeavePage-new" onClick={() => setNewOpen(true)}>
              <Plus className="h-4 w-4" /> {t('leave.newLeave')}
            </Button>
          </div>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryCard label={t('leave.awayToday')} valueAutomationId="LeavePage-away-today">
          {listQuery.data?.summary.away_today ?? 0}
        </SummaryCard>
        <SummaryCard
          label={t('leave.upcomingRequests')}
          valueAutomationId="LeavePage-upcoming-requests"
        >
          {listQuery.data?.summary.upcoming_requests ?? 0}
        </SummaryCard>
        <SummaryCard label={t('leave.upcomingHours')} valueAutomationId="LeavePage-upcoming-hours">
          {listQuery.data?.summary.upcoming_hours ?? 0}
        </SummaryCard>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-3">
          <TabBar
            tabs={leaveTabs}
            activeKey={scope}
            onChange={setScope}
            idPrefix="LeavePage-tab"
            panelId="LeavePage-panel"
          />
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder={t('leave.searchPlaceholder')}
            automationId="LeavePage-search"
            label={t('leave.searchLabel')}
          />
        </div>

        <div id="LeavePage-panel" role="tabpanel" aria-labelledby={`LeavePage-tab-${scope}`}>
          {actionError && <p className="m-3 text-sm text-red-700">{actionError}</p>}
          <QueryState
            isPending={listQuery.isPending}
            isError={listQuery.isError}
            loadingNode={<p className="p-6 text-sm text-slate-500">{t('leave.loading')}</p>}
            errorNode={<p className="p-6 text-sm text-red-700">{t('leave.loadFailed')}</p>}
          >
            {listQuery.data && (
              <LeaveTable
                rows={listQuery.data.requests}
                onEdit={setEditing}
                onCancel={(row) => void cancelRequest(row)}
              />
            )}
          </QueryState>
        </div>
      </section>

      <LeaveRequestDialog
        open={newOpen}
        onOpenChange={setNewOpen}
        staff={staffQuery.data?.staff ?? []}
        leaveTypes={configuredTypes}
        onSaved={refresh}
      />
      <LeaveRequestDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        staff={staffQuery.data?.staff ?? []}
        leaveTypes={configuredTypes}
        request={editing ?? undefined}
        onSaved={async () => {
          setEditing(null)
          await refresh()
        }}
      />
      <OfficeClosureDialog
        open={closureOpen}
        onOpenChange={setClosureOpen}
        onSaved={refresh}
        publicHolidayName={
          // The seed's own default, shown only in the instant before the
          // settings read resolves — not a fallback for missing data: the
          // five codes are seeded by migration.
          settingsQuery.data?.leave_types.find((type) => type.code === 'public_holiday')
            ?.display_name ?? t('leave.publicHolidayDefault')
        }
      />
    </main>
  )
}

function LeaveTable({
  rows,
  onEdit,
  onCancel,
}: {
  rows: LeaveRequestOut[]
  onEdit: (row: LeaveRequestOut) => void
  onCancel: (row: LeaveRequestOut) => void
}) {
  const { t } = useTranslation('timesheet')
  if (rows.length === 0)
    return <p className="p-8 text-center text-sm text-slate-500">{t('leave.empty')}</p>
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr>
            <th className="px-4 py-2">{t('leave.employeeColumn')}</th>
            <th className="px-4 py-2">{t('leave.leaveTypeColumn')}</th>
            <th className="px-4 py-2">{t('leave.datesColumn')}</th>
            <th className="px-4 py-2">{t('leave.hoursColumn')}</th>
            <th className="px-4 py-2">{t('leave.actionsColumn')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-slate-100">
              <td className="px-4 py-3 font-medium text-slate-900">{row.staff_name}</td>
              <td className="px-4 py-3">
                {row.leave_type_name}
                {row.source === 'office_closure' && (
                  <span className="ml-2 rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
                    {t('leave.officeClosureSource')}
                  </span>
                )}
              </td>
              <td className="px-4 py-3">
                {t('leave.dateRange', {
                  start: formatDate(row.start_date),
                  end: formatDate(row.end_date),
                })}
              </td>
              <td className="px-4 py-3">{row.total_hours}</td>
              <td className="space-x-2 px-4 py-3">
                <Button size="sm" variant="outline" onClick={() => onEdit(row)}>
                  {t('leave.edit')}
                </Button>
                <Button size="sm" variant="outline" onClick={() => onCancel(row)}>
                  {t('leave.cancel')}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
