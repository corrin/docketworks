import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { accountsStaffListOptions, type StaffListItemOut } from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { SearchInput } from '@/features/shared/SearchInput'
import { TabBar, type TabBarItem } from '@/features/shared/TabBar'
import { StaffAvatar } from '@/features/shared/StaffAvatar'
import { formatCurrency, formatDate } from '@/lib/format'

import { StaffFormDialog } from './StaffFormDialog'

const HEADER_CELL = 'border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700'
const CELL = 'border-b border-slate-100 px-3 py-2'

type StaffTab = 'current' | 'past'

const STAFF_TABS: readonly TabBarItem<StaffTab>[] = [
  { key: 'current', label: 'Current' },
  { key: 'past', label: 'Past' },
]

/** Opus: is_currently_active, not `date_left === null` — the server carries the
    rule (Staff.is_currently_active) precisely so this screen cannot fork it.
    Someone serving out notice has a leaving date and is still employed, so
    "has a date" and "has left" are different questions. */
function staffStatusLabel(row: StaffListItemOut): string {
  if (row.date_left === null) return 'Active'
  if (row.is_currently_active) return `Leaving ${formatDate(row.date_left)}`
  return `Left ${formatDate(row.date_left)}`
}

/** Opus: Local rather than a shared matcher. The three existing client-side
    match rules (JobPicker.tsx matchesTerm, ProcessFormsPage, ItemSelect) are all
    private for the same reason: the field set IS the rule and differs per screen,
    so a generic helper would share only `.includes`. */
function matchesSearch(row: StaffListItemOut, needle: string): boolean {
  return [
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
        <h1 className="text-2xl font-semibold">Staff</h1>
        <Button onClick={openCreate} data-automation-id="StaffAdminPage-new-staff">
          New staff
        </Button>
      </div>
      <TabBar tabs={STAFF_TABS} activeKey={tab} onChange={setTab} idPrefix="StaffAdminPage-tab" />
      <div>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search staff..."
          automationId="StaffAdminPage-search"
          label="Search staff"
        />
      </div>
      <ListTable
        isPending={staffQuery.isPending}
        isError={staffQuery.isError}
        onRetry={() => void staffQuery.refetch()}
        loadingLabel="staff"
        errorLabel="staff"
        rows={rows}
        emptyLabel={
          search.trim() === '' ? `No ${tab} staff.` : `No ${tab} staff match "${search.trim()}".`
        }
        automationId="StaffAdminPage-table"
        head={
          <tr>
            <th className={HEADER_CELL}>Name</th>
            <th className={HEADER_CELL}>Office email</th>
            <th className={HEADER_CELL}>Started</th>
            <th className={HEADER_CELL}>Costing rate</th>
            <th className={HEADER_CELL}>Status</th>
            <th className={HEADER_CELL}>
              <span className="sr-only">Actions</span>
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
                Edit
              </Button>
            </td>
          </tr>
        )}
      />
      <StaffFormDialog open={dialogOpen} onOpenChange={setDialogOpen} staff={editing} />
    </div>
  )
}
