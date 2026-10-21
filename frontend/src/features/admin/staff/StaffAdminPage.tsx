import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { accountsStaffListOptions, type StaffListItemOut } from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { SearchInput } from '@/features/shared/SearchInput'
import { TabBar, type TabBarItem } from '@/features/shared/TabBar'
import { StaffAvatar } from '@/features/shared/StaffAvatar'
import { formatCurrency, formatDate } from '@/lib/format'
import { i18n } from '@/lib/i18n'

import { StaffFormDialog } from './StaffFormDialog'

const HEADER_CELL = 'border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700'
const CELL = 'border-b border-slate-100 px-3 py-2'

type StaffTab = 'current' | 'past'

const STAFF_TAB_KEYS: readonly StaffTab[] = ['current', 'past']

/** Opus: is_currently_active, not `date_left === null` — the server carries the
    rule (Staff.is_currently_active) precisely so this screen cannot fork it.
    Someone serving out notice has a leaving date and is still employed, so
    "has a date" and "has left" are different questions. */
function staffStatusLabel(row: StaffListItemOut): string {
  if (row.date_left === null) return i18n.t('admin:staffList.status.active')
  if (row.is_currently_active)
    return i18n.t('admin:staffList.status.leaving', { date: formatDate(row.date_left) })
  return i18n.t('admin:staffList.status.left', { date: formatDate(row.date_left) })
}

/** Opus: Local rather than a shared matcher. The three existing client-side
    match rules (JobPicker.tsx matchesTerm, ProcessFormsPage, ItemSelect) are all
    private for the same reason: the field set IS the rule and differs per screen,
    so a generic helper would share only `.includes`. */
function matchesSearch(row: StaffListItemOut, needle: string): boolean {
  return [
    // The Name cell renders `first_name last_name` and the avatar's tooltip
    // renders display_name, so both are searchable: matching only the parts
    // means typing the name you can see finds nothing.
    `${row.first_name} ${row.last_name}`,
    row.display_name,
    row.first_name,
    row.last_name,
    row.preferred_name,
    row.office_email,
    row.payroll_email,
  ].some((field) => (field ?? '').toLowerCase().includes(needle))
}

/**
 * The staff admin list (/admin/staff): the staff table split into Current and
 * Past tabs over one query, with a quick filter and a create/edit modal.
 * Superuser surface — the navbar gate and every endpoint behind it agree.
 */
export function StaffAdminPage() {
  const { t } = useTranslation('admin')
  const staffTabs: readonly TabBarItem<StaffTab>[] = STAFF_TAB_KEYS.map((key) => ({
    key,
    label: t(`staffList.tabs.${key}`),
  }))
  const staffQuery = useQuery(accountsStaffListOptions())
  const [tab, setTab] = useState<StaffTab>('current')
  const [search, setSearch] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  // The row being edited, or null for create. Kept when the dialog closes so
  // the closing animation does not flash the empty create form.
  const [editing, setEditing] = useState<StaffListItemOut | null>(null)

  const openCreate = (): void => {
    setEditing(null)
    setDialogOpen(true)
  }

  const openEdit = (row: StaffListItemOut): void => {
    setEditing(row)
    setDialogOpen(true)
  }

  // Opus: Filtered client-side over the one unparameterised query rather than a
  // `q`/tab param on accounts_staff_list: production holds 27 staff rows
  // (docs/prod-data-shape.yml), and StaffFormDialog writes a created row straight
  // into this query's cache — a per-tab or per-term query key would strand that
  // write in a cache the visible list never reads. Server-side `q` is the shape
  // to reach for if this list ever outgrows one page.
  //
  // Opus: No useDebouncedValue either, unlike the six server-backed search boxes:
  // there is no round trip to delay, so 300ms of lag would buy nothing. It goes
  // back in the moment this queries the server.
  const rows = useMemo(() => {
    const all = staffQuery.data
    if (all === undefined) return undefined
    const needle = search.trim().toLowerCase()
    return all.filter(
      (row) =>
        row.is_currently_active === (tab === 'current') &&
        (needle === '' || matchesSearch(row, needle)),
    )
  }, [staffQuery.data, tab, search])

  return (
    <div
      className="mx-auto flex max-w-5xl flex-col gap-4 p-6"
      data-automation-id="StaffAdminPage-root"
    >
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('staffList.title')}</h1>
        <Button onClick={openCreate} data-automation-id="StaffAdminPage-new-staff">
          {t('staffList.newStaff')}
        </Button>
      </div>
      <TabBar
        tabs={staffTabs}
        activeKey={tab}
        onChange={setTab}
        idPrefix="StaffAdminPage-tab"
        panelId="StaffAdminPage-panel"
      />
      <div id="StaffAdminPage-panel" role="tabpanel" aria-labelledby={`StaffAdminPage-tab-${tab}`}>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={t('staffList.searchPlaceholder')}
          automationId="StaffAdminPage-search"
          label={t('staffList.searchLabel')}
        />
        <ListTable
          isPending={staffQuery.isPending}
          isError={staffQuery.isError}
          onRetry={() => void staffQuery.refetch()}
          loadingLabel={t('staffList.loadingLabel')}
          errorLabel={t('staffList.errorLabel')}
          rows={rows}
          emptyLabel={
            search.trim() === ''
              ? t(`staffList.empty.${tab}`)
              : t(`staffList.noMatch.${tab}`, { term: search.trim() })
          }
          automationId="StaffAdminPage-table"
          head={
            <tr>
              <th className={HEADER_CELL}>{t('staffList.columns.name')}</th>
              <th className={HEADER_CELL}>{t('staffList.columns.officeEmail')}</th>
              <th className={HEADER_CELL}>{t('staffList.columns.started')}</th>
              <th className={HEADER_CELL}>{t('staffList.columns.costingRate')}</th>
              <th className={HEADER_CELL}>{t('staffList.columns.status')}</th>
              <th className={HEADER_CELL}>
                <span className="sr-only">{t('staffList.columns.actions')}</span>
              </th>
            </tr>
          }
          renderRow={(row) => (
            <tr key={row.id} data-automation-id={`StaffAdminPage-row-${row.id}`}>
              <td className={CELL}>
                <div className="flex items-center gap-2">
                  <StaffAvatar
                    person={{ id: row.id, display_name: row.display_name, icon_url: row.icon_url }}
                  />
                  <span>
                    {row.first_name} {row.last_name}
                  </span>
                </div>
              </td>
              <td className={CELL}>{row.office_email ?? row.payroll_email}</td>
              <td className={CELL}>{formatDate(row.employment_start_date)}</td>
              <td className={CELL}>{formatCurrency(row.wage_rate)}</td>
              <td className={CELL}>{staffStatusLabel(row)}</td>
              <td className={CELL}>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => openEdit(row)}
                  data-automation-id={`StaffAdminPage-edit-staff-${row.id}`}
                >
                  {t('staffList.edit')}
                </Button>
              </td>
            </tr>
          )}
        />
      </div>
      <StaffFormDialog open={dialogOpen} onOpenChange={setDialogOpen} staff={editing} />
    </div>
  )
}
