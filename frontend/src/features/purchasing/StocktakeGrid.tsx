import {
  createColumnHelper,
  useTable,
  type CellContext,
  type RowData,
  type TableFeatures,
} from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { DataTable } from '@/features/shared/DataTable'
import { editableGridFeatures } from '@/features/shared/editableGridTable'
import { trimDecimal } from '@/features/shared/decimal'
import { formatCurrency } from '@/lib/format'
import type { StockItem, StocktakeLineWrite } from '@/api'

export type CountRow = StocktakeLineWrite & { unitCostInput: string; countInput: string }
interface CountContext {
  readOnly: boolean
  update: (id: string, patch: Partial<CountRow>) => void
  remove: (id: string) => void
  current: ReadonlyMap<string, StockItem>
  recount: (id: string) => void
}
declare module '@tanstack/react-table' {
  interface TableMeta<TFeatures extends TableFeatures, TData extends RowData> {
    stocktakeGrid?: CountContext
  }
}
function context(cell: CellContext<typeof editableGridFeatures, CountRow>): CountContext {
  const value = cell.table.options.meta?.stocktakeGrid
  if (!value) throw new Error('Stocktake grid context is required')
  return value
}
const helper = createColumnHelper<typeof editableGridFeatures, CountRow>()
const columns = [
  helper.display({
    id: 'description',
    header: 'Item',
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label="Item description"
          className={INPUT_CLASS}
          value={row.description}
          readOnly={ctx.readOnly || row.stock_id !== null}
          onChange={(e) => ctx.update(row.id, { description: e.target.value })}
        />
      )
    },
  }),
  helper.display({
    id: 'location',
    header: 'Location',
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label="Count location"
          className={INPUT_CLASS}
          value={row.location ?? ''}
          readOnly={ctx.readOnly || row.stock_id !== null}
          onChange={(e) => ctx.update(row.id, { location: e.target.value.trim() || null })}
        />
      )
    },
  }),
  helper.display({
    id: 'expected',
    header: 'Recorded',
    cell: (cell) => trimDecimal(String(cell.row.original.expected_quantity)),
  }),
  helper.display({
    id: 'counted',
    header: 'Counted',
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label="Counted quantity"
          type="number"
          min="0"
          step="0.001"
          className={INPUT_CLASS}
          value={row.countInput}
          readOnly={ctx.readOnly}
          onChange={(e) =>
            ctx.update(row.id, {
              countInput: e.target.value,
              counted_quantity: e.target.value === '' ? null : Number(e.target.value),
            })
          }
        />
      )
    },
  }),
  helper.display({
    id: 'cost',
    header: 'Unit cost',
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label="Unit cost"
          type="number"
          min="0"
          step="0.01"
          className={INPUT_CLASS}
          value={row.unitCostInput}
          readOnly={ctx.readOnly || row.stock_id !== null}
          onChange={(e) =>
            ctx.update(row.id, { unitCostInput: e.target.value, unit_cost: Number(e.target.value) })
          }
        />
      )
    },
  }),
  helper.display({
    id: 'difference',
    header: 'Difference',
    cell: (cell) => {
      const row = cell.row.original
      return row.counted_quantity === null
        ? 'Uncounted'
        : trimDecimal(String(row.counted_quantity - row.expected_quantity))
    },
  }),
  helper.display({
    id: 'value',
    header: 'Value',
    cell: (cell) => {
      const row = cell.row.original
      return row.counted_quantity === null || row.unitCostInput === ''
        ? '—'
        : formatCurrency((row.counted_quantity - row.expected_quantity) * row.unit_cost)
    },
  }),
  helper.display({
    id: 'reason',
    header: 'Reason',
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label="Difference reason"
          className={INPUT_CLASS}
          value={row.reason ?? ''}
          readOnly={ctx.readOnly}
          placeholder="Unexplained surplus / shortage"
          onChange={(e) => ctx.update(row.id, { reason: e.target.value || null })}
        />
      )
    },
  }),
  helper.display({
    id: 'actions',
    header: 'Review',
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      if (ctx.readOnly) return null
      const current = row.stock_id === null ? undefined : ctx.current.get(row.stock_id)
      const stale =
        current &&
        (current.inventory_version !== row.expected_version ||
          Number(current.quantity) !== row.expected_quantity ||
          Number(current.unit_cost) !== row.unit_cost)
      return (
        <div className="space-y-2">
          {stale && (
            <>
              <p className="text-amber-800">
                Stock changed: now {trimDecimal(current.quantity)}. Recount required.
              </p>
              <Button size="sm" variant="outline" onClick={() => ctx.recount(row.id)}>
                Recount
              </Button>
            </>
          )}
          <Button size="sm" variant="ghost" onClick={() => ctx.remove(row.id)}>
            Remove
          </Button>
        </div>
      )
    },
  }),
]
const editable = new Set(['description', 'location', 'counted', 'cost', 'reason'])
export function StocktakeGrid({ rows, ...meta }: CountContext & { rows: CountRow[] }) {
  const table = useTable({
    features: editableGridFeatures,
    data: rows,
    columns,
    getRowId: (row) => row.id,
    meta: { stocktakeGrid: meta },
  })
  return (
    <DataTable
      table={table}
      editableColumns={editable}
      draftLocalId={() => null}
      rowExitHandlers={() => ({ onBlur: () => {}, onFocus: () => {} })}
      wrapperClassName="max-h-[60vh]"
      tableClassName="min-w-[1100px] table-fixed"
      columnLayout={{
        description: { widthClassName: 'w-[25%]' },
        location: { widthClassName: 'w-36' },
        expected: { widthClassName: 'w-20' },
        counted: { widthClassName: 'w-24' },
        cost: { widthClassName: 'w-24' },
        difference: { widthClassName: 'w-20' },
        value: { widthClassName: 'w-24' },
        reason: { widthClassName: 'w-[20%]' },
        actions: { widthClassName: 'w-28' },
      }}
    />
  )
}
