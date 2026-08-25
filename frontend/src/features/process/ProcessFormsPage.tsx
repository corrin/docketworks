import { useMemo, useState } from 'react'
import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'

import { processFormsListOptions, type FormOut } from '@/api'
import { Button } from '@/components/ui/button'
import { meQueryOptions } from '@/features/auth'
import { ListTable } from '@/features/shared/ListTable'
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from '@/features/shared/useDebouncedValue'
import { formatDate } from '@/lib/format'

import { FormDialog, requireCategory } from './FormDialog'

const HEADER_CELL = 'border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700'
const CELL = 'border-b border-slate-100 px-3 py-2'

/**
 * A category's form/register list (/process-documents/forms/:category):
 * search, an archived toggle, and a create/edit dialog whose schema editor
 * fixes v1's defect of never loading or saving `form_schema`.
 */
export function ProcessFormsPage({ category }: { category: string }) {
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const navigate = useNavigate()
  const [searchInput, setSearchInput] = useState('')
  const searchQuery = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS)
  const [showArchived, setShowArchived] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  // The row being edited, or null for create. Kept when the dialog closes so
  // the closing animation does not flash the empty create form.
  const [editing, setEditing] = useState<FormOut | null>(null)

  const formsQuery = useQuery(
    processFormsListOptions({
      query: {
        category: requireCategory(category),
        ...(showArchived ? { status: 'archived' as const } : {}),
      },
    }),
  )

  // Client-side filter, not a server round trip: a category's form list runs
  // ~30 rows, so a debounced local .filter() is simpler than adding another
  // query variant (and its own loading/error state) for a box this small —
  // process_forms_list's own `q` param stays unused here.
  const rows = useMemo(() => {
    const all = formsQuery.data
    if (all === undefined) return undefined
    const needle = searchQuery.trim().toLowerCase()
    if (needle === '') return all
    return all.filter(
      (form) =>
        form.title.toLowerCase().includes(needle) ||
        (form.document_number ?? '').toLowerCase().includes(needle),
    )
  }, [formsQuery.data, searchQuery])

  const openCreate = (): void => {
    setEditing(null)
    setDialogOpen(true)
  }

  const openEdit = (form: FormOut): void => {
    setEditing(form)
    setDialogOpen(true)
  }

  return (
    <div className="min-h-screen p-6" data-automation-id="ProcessFormsPage-root">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">Forms</h1>
        <Button onClick={openCreate} data-automation-id="ProcessFormsPage-new-form">
          New Form
        </Button>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4">
        <input
          type="text"
          placeholder="Search forms..."
          value={searchInput}
          autoComplete="off"
          data-automation-id="ProcessFormsPage-search"
          className="w-full max-w-md rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
          onChange={(event) => setSearchInput(event.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.target.checked)}
            data-automation-id="ProcessFormsPage-show-archived"
          />
          Show archived
        </label>
      </div>

      <ListTable
        isPending={formsQuery.isPending}
        isError={formsQuery.isError}
        onRetry={() => void formsQuery.refetch()}
        loadingLabel="Loading forms..."
        errorLabel="Failed to load forms."
        rows={rows}
        emptyLabel="No forms found"
        automationId="ProcessFormsPage-table"
        head={
          <tr>
            <th className={HEADER_CELL}>Title</th>
            <th className={HEADER_CELL}>Doc #</th>
            <th className={HEADER_CELL}>Tags</th>
            <th className={HEADER_CELL}>Entries</th>
            <th className={HEADER_CELL}>Updated</th>
            <th className={HEADER_CELL}>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        }
        renderRow={(form) => (
          <tr
            key={form.id}
            data-automation-id={`ProcessFormsPage-row-${form.id}`}
            className="cursor-pointer hover:bg-blue-50"
            onClick={() => {
              void navigate({
                to: '/process-documents/forms/$category/$formId',
                params: { category, formId: form.id },
              })
            }}
          >
            <td className={`${CELL} font-medium text-gray-900`}>
              {/* A real link so keyboard users can open the entries page; the
                  row onClick is the mouse-only whole-row affordance (same
                  pattern as PoListPage/CompaniesListPage). */}
              <Link
                to="/process-documents/forms/$category/$formId"
                params={{ category, formId: form.id }}
                className="hover:underline"
                onClick={(event) => event.stopPropagation()}
              >
                {form.title}
              </Link>
            </td>
            <td className={CELL}>{form.document_number ?? '—'}</td>
            <td className={CELL}>{form.tags.join(', ') || '—'}</td>
            <td className={`${CELL} text-right tabular-nums`}>{form.entry_count}</td>
            <td className={CELL}>{formatDate(form.updated_at)}</td>
            <td className={CELL} onClick={(event) => event.stopPropagation()}>
              <div className="flex gap-2">
                {/* Placeholder: opens the Task 12 EntryForm in a dialog for
                    this form. Any staff may fill a form (entry writes are
                    CookieJWTAuth), so the button itself has no gate — it is
                    only disabled because that dialog does not exist yet. */}
                <Button
                  variant="outline"
                  size="sm"
                  disabled
                  title="Wired up in Task 12."
                  data-automation-id={`ProcessFormsPage-fill-${form.id}`}
                >
                  Fill
                </Button>
                {/* Office-only: process_forms_partial_update uses
                    OfficeStaffCookieJWTAuth, matching this gate. The API
                    rejects a non-office write regardless. */}
                {user.is_office_staff && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => openEdit(form)}
                    data-automation-id={`ProcessFormsPage-edit-${form.id}`}
                  >
                    Edit
                  </Button>
                )}
              </div>
            </td>
          </tr>
        )}
      />
      <FormDialog open={dialogOpen} onOpenChange={setDialogOpen} form={editing} />
    </div>
  )
}
