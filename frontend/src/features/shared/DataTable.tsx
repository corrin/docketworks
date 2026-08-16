import { flexRender, type RowData, type Table } from '@tanstack/react-table'

import type { editableGridFeatures } from './editableGridTable'
import type { RowExitBlurEvent } from './useDraftRows'

interface RowExitHandlers {
  onBlur: (event: RowExitBlurEvent) => void
  onFocus: () => void
}

interface DataTableProps<TRow extends RowData> {
  table: Table<typeof editableGridFeatures, TRow>
  /** Column ids whose cells carry the data-grid-* keyboard-nav contract. */
  editableColumns: ReadonlySet<string>
  /** The localId of an unpersisted draft row (arms row-exit commit wiring),
      null for server rows. */
  draftLocalId: (row: TRow) => string | null
  /** useDraftRows' row-exit wiring for draft rows. */
  rowExitHandlers: (localId: string) => RowExitHandlers
  /** Marker class on the scroll wrapper (e.g. 'smart-timesheet-table'). */
  wrapperClassName?: string
  /** Marker class on the table element (e.g. 'smart-costlines-table'). */
  tableClassName?: string
}

/**
 * The one owner of the editable-grid E2E contract: `DataTable-row-N` +
 * `data-row-id` per row, and `data-grid-nav-cell` / `data-grid-row` /
 * `data-grid-col` on editable cells. Every draft-row grid (timesheet, cost
 * lines, PO lines) renders through it; plain read-only list pages are
 * deliberately NOT consumers — they carry none of this contract, and plain
 * markup there beats indirection.
 *
 * The automation index is the VISUAL row index derived at render time:
 * consumers use the core row model with no sorting or filtering, so data
 * order IS visual order, and a memoised copy would go stale.
 *
 * Consumers must keep their column definitions module-constant — rebuilding
 * them per render would change every cell component's identity and remount
 * (blurring) all inputs on each render. Live state reaches cells via table
 * meta instead.
 *
 * Plain read-only list pages (companies, purchase orders, stock, WIP
 * report) do NOT consume this — they carry none of the draft/grid-nav
 * contract and forcing them through react-table's column-def ceremony would
 * be indirection, not rigor. They render through the deliberately simpler
 * `ListTable` (`features/shared/ListTable.tsx`) instead.
 */
export function DataTable<TRow extends RowData>({
  table,
  editableColumns,
  draftLocalId,
  rowExitHandlers,
  wrapperClassName,
  tableClassName,
}: DataTableProps<TRow>) {
  return (
    <div className={joinClasses(wrapperClassName, 'overflow-x-auto')}>
      <table className={joinClasses(tableClassName, 'min-w-full text-sm')}>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-slate-200 bg-slate-50">
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  className="px-2 py-2 text-left text-xs font-semibold text-slate-600"
                >
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row, rowIndex) => {
            // Focus leaving the whole ROW is the create gesture for typed
            // drafts — the deferred commit and its cancellation live in
            // useDraftRows.
            const localId = draftLocalId(row.original)
            const exitHandlers = localId !== null ? rowExitHandlers(localId) : undefined
            return (
              <tr
                key={row.id}
                data-automation-id={`DataTable-row-${rowIndex}`}
                data-row-id={row.id}
                className="border-b border-slate-100 align-top hover:bg-slate-50"
                {...exitHandlers}
              >
                {row.getVisibleCells().map((cell) => {
                  const columnId = cell.column.id
                  const editable = editableColumns.has(columnId)
                  return (
                    <td
                      key={cell.id}
                      className="px-2 py-1"
                      {...(editable
                        ? {
                            'data-grid-nav-cell': 'true',
                            'data-grid-row': rowIndex,
                            'data-grid-col': columnId,
                          }
                        : {})}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function joinClasses(marker: string | undefined, base: string): string {
  return marker ? `${marker} ${base}` : base
}
