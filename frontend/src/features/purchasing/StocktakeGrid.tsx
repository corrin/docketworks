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
import { formatCurrency, formatQuantity } from '@/lib/format'
import { i18n } from '@/lib/i18n'
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
    header: () => i18n.t('purchasing:stocktakeGrid.header.item'),
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label={i18n.t('purchasing:stocktakeGrid.itemDescription')}
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
    header: () => i18n.t('purchasing:stocktakeGrid.header.location'),
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label={i18n.t('purchasing:stocktakeGrid.countLocation')}
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
    header: () => i18n.t('purchasing:stocktakeGrid.header.recorded'),
    cell: (cell) => trimDecimal(String(cell.row.original.expected_quantity)),
  }),
  helper.display({
    id: 'counted',
    header: () => i18n.t('purchasing:stocktakeGrid.header.counted'),
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label={i18n.t('purchasing:stocktakeGrid.countedQuantity')}
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
    header: () => i18n.t('purchasing:stocktakeGrid.header.unitCost'),
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label={i18n.t('purchasing:stocktakeGrid.unitCost')}
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
    header: () => i18n.t('purchasing:stocktakeGrid.header.difference'),
    cell: (cell) => {
      const row = cell.row.original
      return row.counted_quantity === null
        ? i18n.t('purchasing:stocktakeGrid.uncounted')
        : formatQuantity(row.counted_quantity - row.expected_quantity)
    },
  }),
  helper.display({
    id: 'value',
    header: () => i18n.t('purchasing:stocktakeGrid.header.value'),
    cell: (cell) => {
      const row = cell.row.original
      return row.counted_quantity === null || row.unitCostInput === ''
        ? i18n.t('purchasing:stocktakeGrid.noValue')
        : formatCurrency((row.counted_quantity - row.expected_quantity) * row.unit_cost)
    },
  }),
  helper.display({
    id: 'reason',
    header: () => i18n.t('purchasing:stocktakeGrid.header.reason'),
    cell: (cell) => {
      const row = cell.row.original
      const ctx = context(cell)
      return (
        <input
          aria-label={i18n.t('purchasing:stocktakeGrid.differenceReason')}
          className={INPUT_CLASS}
          value={row.reason ?? ''}
          readOnly={ctx.readOnly}
          placeholder={i18n.t('purchasing:stocktakeGrid.reasonPlaceholder')}
          onChange={(e) => ctx.update(row.id, { reason: e.target.value || null })}
        />
      )
    },
  }),
  helper.display({
    id: 'actions',
    header: () => i18n.t('purchasing:stocktakeGrid.header.review'),
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
                {i18n.t('purchasing:stocktakeGrid.stockChanged', {
                  quantity: trimDecimal(current.quantity),
                })}
              </p>
              <Button size="sm" variant="outline" onClick={() => ctx.recount(row.id)}>
                {i18n.t('purchasing:stocktakeGrid.recount')}
              </Button>
            </>
          )}
          <Button size="sm" variant="ghost" onClick={() => ctx.remove(row.id)}>
            {i18n.t('purchasing:stocktakeGrid.remove')}
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
