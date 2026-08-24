import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { accountsStaffListOptions, type StaffListItemOut } from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { StaffAvatar } from '@/features/shared/StaffAvatar'
import { formatCurrency, formatDate } from '@/lib/format'

import { StaffFormDialog } from './StaffFormDialog'

const HEADER_CELL = 'border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700'
const CELL = 'border-b border-slate-100 px-3 py-2'

/**
 * The staff admin list (/admin/staff): the whole staff table, departed members
 * included, with a create/edit modal. Superuser surface — the navbar gate and
 * every endpoint behind it agree.
 */
export function StaffAdminPage() {
  const staffQuery = useQuery(accountsStaffListOptions())
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
      <ListTable
        isPending={staffQuery.isPending}
        isError={staffQuery.isError}
        onRetry={() => void staffQuery.refetch()}
        loadingLabel="staff"
        errorLabel="staff"
        rows={staffQuery.data}
        emptyLabel="No staff members."
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
                  person={{
                    id: row.id,
                    display_name: `${row.preferred_name ?? row.first_name} ${row.last_name}`,
                    icon_url: row.icon_url,
                  }}
                />
                <span>
                  {row.first_name} {row.last_name}
                </span>
              </div>
            </td>
            <td className={CELL}>{row.office_email}</td>
            <td className={CELL}>{formatDate(row.employment_start_date)}</td>
            <td className={CELL}>{formatCurrency(row.wage_rate)}</td>
            <td className={CELL}>
              {row.date_left === null ? 'Active' : `Left ${formatDate(row.date_left)}`}
            </td>
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
