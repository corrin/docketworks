import type { ReactNode } from 'react'

import { QueryState } from './QueryState'

interface ListTableProps<TRow> {
  isPending: boolean
  isError: boolean
  /** Omit for a static "Reload the page." message; pass the query's
      refetch for a working Retry button. */
  onRetry?: () => void
  loadingLabel: string
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
 * The one owner of the plain, query-backed read-only table: the table shell
 * classes and the empty-rows message, layered over `QueryState`
 * (`features/shared/QueryState.tsx`) for the loading/error gate every
 * query-backed surface shares. Deliberately separate from `DataTable`
 * (`features/shared/DataTable.tsx`), which wraps a `@tanstack/react-table`
 * instance for editable draft grids — forcing a plain static list through
 * that column-def/cell-context machinery would be indirection, not rigor.
 * Callers own only their header and row markup.
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
  return (
    <QueryState
      isPending={isPending}
      isError={isError}
      onRetry={onRetry}
      loadingLabel={loadingLabel}
      loadingAutomationId={loadingAutomationId}
      errorLabel={errorLabel}
    >
      {rows !== undefined && (
        <>
          {children}
          <div className="mt-6 overflow-x-auto">
            <table data-automation-id={automationId} className="w-full border-collapse text-sm">
              <thead>{head}</thead>
              <tbody>{rows.map(renderRow)}</tbody>
            </table>
            {rows.length === 0 && (
              <div className="mt-8 text-center text-gray-500">{emptyLabel}</div>
            )}
          </div>
        </>
      )}
    </QueryState>
  )
}
