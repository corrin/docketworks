import { useTranslation } from 'react-i18next'

import type { EntryOut, FormFieldSchema } from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { formatDate } from '@/lib/format'

import { textFor } from './entryValue'

const HEADER_CELL = 'border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700'
const CELL = 'border-b border-slate-100 px-3 py-2'

interface Props {
  schema: FormFieldSchema[]
  isPending: boolean
  isError: boolean
  onRetry: () => void
  rows: EntryOut[] | undefined
  /** The row currently mid-archive, so its own button (only) shows the busy
      label instead of every row disabling at once. */
  archivingId: string | null
  onEdit: (entry: EntryOut) => void
  onHistory: (entry: EntryOut) => void
  onLinks: (entry: EntryOut) => void
  onArchive: (entry: EntryOut) => void
}

/** One schema field's cell value: the server-resolved display label first
    (a staff/entry_ref UUID rendered as a name), the raw stored value only
    when there is nothing to resolve. */
function fieldValue(entry: EntryOut, key: string): string {
  const displayed = entry.display_data[key]
  if (displayed !== undefined) return displayed
  const text = textFor(entry.data[key])
  return text === '' ? '-' : text
}

/**
 * The entries page's paginated row list. A plain `ListTable` (not
 * `DataTable`'s editable-grid machinery, ADR 0039 — CLAUDE.md/features/shared/
 * ListTable.tsx docstring): every write here opens a dialog rather than
 * editing in place.
 */
export function EntriesTable({
  schema,
  isPending,
  isError,
  onRetry,
  rows,
  archivingId,
  onEdit,
  onHistory,
  onLinks,
  onArchive,
}: Props) {
  const { t } = useTranslation('process')
  return (
    <ListTable
      isPending={isPending}
      isError={isError}
      onRetry={onRetry}
      loadingLabel={t('entriesTable.loading')}
      errorLabel={t('entriesTable.loadFailed')}
      rows={rows}
      emptyLabel={t('entriesTable.empty')}
      automationId="EntriesTable-table"
      head={
        <tr>
          {schema.map((field) => (
            <th key={field.key} className={HEADER_CELL}>
              {field.label}
            </th>
          ))}
          <th className={HEADER_CELL}>{t('entriesTable.date')}</th>
          <th className={HEADER_CELL}>{t('entriesTable.staff')}</th>
          <th className={HEADER_CELL}>{t('entriesTable.enteredBy')}</th>
          <th className={HEADER_CELL}>{t('entriesTable.links')}</th>
          <th className={HEADER_CELL}>
            <span className="sr-only">{t('entriesTable.actions')}</span>
          </th>
        </tr>
      }
      renderRow={(entry) => (
        <tr key={entry.id} data-automation-id={`EntriesTable-row-${entry.id}`}>
          {schema.map((field) => (
            <td key={field.key} className={CELL}>
              {fieldValue(entry, field.key)}
            </td>
          ))}
          <td className={CELL}>{formatDate(entry.entry_date)}</td>
          <td className={CELL}>{entry.staff_name ?? '-'}</td>
          <td className={CELL}>{entry.entered_by_name ?? '-'}</td>
          <td className={`${CELL} text-right tabular-nums`}>{entry.child_count}</td>
          <td className={CELL}>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => onEdit(entry)}
                data-automation-id={`EntriesTable-edit-${entry.id}`}
              >
                {t('entriesTable.edit')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onHistory(entry)}
                data-automation-id={`EntriesTable-history-${entry.id}`}
              >
                {t('entriesTable.history')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onLinks(entry)}
                data-automation-id={`EntriesTable-links-${entry.id}`}
              >
                {t('entriesTable.links')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={archivingId === entry.id}
                onClick={() => onArchive(entry)}
                data-automation-id={`EntriesTable-archive-${entry.id}`}
              >
                {archivingId === entry.id ? t('entriesTable.archiving') : t('entriesTable.archive')}
              </Button>
            </div>
          </td>
        </tr>
      )}
    />
  )
}
