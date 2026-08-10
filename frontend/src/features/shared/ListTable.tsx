import type { ReactNode } from 'react'

interface ListTableProps<TRow> {
  isPending: boolean
  isError: boolean
  /** Omit for a static "Reload the page." message; pass the query's
      refetch for a working Retry button. */
  onRetry?: () => void
  loadingLabel: string
  /** The loading element's data-automation-id — must unmount (not just
      hide) once loaded, since the E2E contract waits on it leaving the
      tree; only WipReportPage's spec asserts one today. */
  loadingAutomationId?: string
  errorLabel: string
  rows: readonly TRow[] | undefined
  emptyLabel: string
  /** The table element's own data-automation-id, where a spec asserts one. */
  automationId?: string
  /** The header row's content — sortable or not is the caller's choice;
      ListTable owns no sort state. */
  head: ReactNode
  renderRow: (row: TRow) => ReactNode
  /** Extra content rendered above the table once loaded (e.g. the WIP
      report's summary cards) — omit for the common rows-only case. */
  children?: ReactNode
}

/**
 * The one owner of the plain, query-backed read-only table: loading text,
 * error text with an optional Retry, the table shell classes, and the
 * empty-rows message — previously hand-duplicated across every list page.
 * Deliberately separate from `DataTable` (`features/shared/DataTable.tsx`),
 * which wraps a `@tanstack/react-table` instance for editable draft grids —
 * forcing a plain static list through that column-def/cell-context
 * machinery would be indirection, not rigor. Callers own only their header
 * and row markup.
 */
export function ListTable<TRow>({
  isPending,
  isError,
  onRetry,
  loadingLabel,
  loadingAutomationId,
  errorLabel,
  rows,
  emptyLabel,
  automationId,
  head,
  renderRow,
  children,
}: ListTableProps<TRow>) {
  if (isPending) {
    return (
      <div data-automation-id={loadingAutomationId} className="mt-8 text-gray-500">
        {loadingLabel}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="mt-8 text-red-600">
        {errorLabel}
        {onRetry ? (
          <button type="button" className="ml-2 underline" onClick={onRetry}>
            Retry
          </button>
        ) : (
          ' Reload the page.'
        )}
      </div>
    )
  }

  if (rows === undefined) {
    return null
  }

  return (
    <>
      {children}
      <div className="mt-6 overflow-x-auto">
        <table data-automation-id={automationId} className="w-full border-collapse text-sm">
          <thead>{head}</thead>
          <tbody>{rows.map(renderRow)}</tbody>
        </table>
        {rows.length === 0 && <div className="mt-8 text-center text-gray-500">{emptyLabel}</div>}
      </div>
    </>
  )
}
