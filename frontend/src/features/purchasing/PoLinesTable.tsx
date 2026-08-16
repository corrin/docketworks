import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  createColumnHelper,
  useTable,
  type CellContext,
  type RowData,
  type Table,
  type TableFeatures,
} from '@tanstack/react-table'

import { purchasingAllJobsRetrieveOptions } from '@/api'
import type { PurchaseOrderLineOut, JobForPurchasing, StockItem } from '@/api'
import { DataTable } from '@/features/shared/DataTable'
import { editableGridFeatures } from '@/features/shared/editableGridTable'
import { parseDecimalInput, trimDecimal } from '@/features/shared/decimal'
import { ItemSelect } from '@/features/shared/ItemSelect'
import { SaveFailedBadge } from '@/features/shared/SaveFailedBadge'
import { useAutosaveField } from '@/features/shared/useAutosaveField'
import { useDraftRows, type DraftEntry } from '@/features/shared/useDraftRows'
import { formatCurrency } from '@/lib/format'
import { JobSelect } from './JobSelect'
import {
  emptyPoLineDraft,
  poLineDraftIsEmpty,
  poLineDraftIsReady,
  poLineItemLabel,
  type PoLineDraft,
} from './lines'
import type { PoLinePatch } from './usePoLines'

type GridRow =
  { type: 'server'; line: PurchaseOrderLineOut } | ({ type: 'draft' } & DraftEntry<PoLineDraft>)

interface CreateLineCallbacks {
  onCreated: () => void
  onFailed: () => void
}

interface PoLinesTableProps {
  lines: readonly PurchaseOrderLineOut[]
  readOnly?: boolean
  patchLine: (lineId: string, body: PoLinePatch, display?: Partial<PurchaseOrderLineOut>) => void
  createLine: (draft: PoLineDraft, callbacks: CreateLineCallbacks) => void
}

interface GridCellContext {
  readOnly: boolean
  jobs: readonly JobForPurchasing[]
  jobsLoading: boolean
  patchLine: PoLinesTableProps['patchLine']
  updateDraft: (localId: string, patch: Partial<PoLineDraft>) => void
  isPhantom: (localId: string) => boolean
  isPersisting: (localId: string) => boolean
  isFailed: (localId: string) => boolean
}

function rowLocked(context: GridCellContext, gridRow: GridRow): boolean {
  if (context.readOnly) return true
  return gridRow.type === 'draft' && context.isPersisting(gridRow.localId)
}

declare module '@tanstack/react-table' {
  // Namespaced (not `extends`): TableMeta merges globally across every grid
  // in the app, so a flat extension here would force the other grids' meta
  // to satisfy this grid's context and vice versa.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface TableMeta<TFeatures extends TableFeatures, TData extends RowData> {
    poGrid?: GridCellContext
  }
}

/**
 * The PO line grid: server lines then drafts, with exactly one trailing
 * empty phantom row and no add-line button (the wire contract asserts the
 * button's absence). Typed drafts persist on row EXIT only — in this grid
 * that includes the spec's Tab out of unit-cost, because unit-cost is the
 * row's last focusable cell (line delete is deferred scope, so no trailing
 * action button swallows the Tab).
 */
export function PoLinesTable({
  lines,
  readOnly = false,
  patchLine,
  createLine,
}: PoLinesTableProps) {
  const jobsQuery = useQuery(purchasingAllJobsRetrieveOptions())

  const draftRows = useDraftRows<PoLineDraft>({
    emptyDraft: emptyPoLineDraft,
    draftIsEmpty: poLineDraftIsEmpty,
    isReady: poLineDraftIsReady,
    persist: (draft, callbacks) => createLine(draft, callbacks),
  })

  const rows = useMemo<GridRow[]>(
    () => [
      ...lines.map((line): GridRow => ({ type: 'server', line })),
      ...draftRows.drafts.map((entry): GridRow => ({ type: 'draft', ...entry })),
    ],
    [lines, draftRows.drafts],
  )

  // Fresh every render so handlers close over current state; passed as table
  // meta, which cells read at render/event time. The COLUMN definitions stay
  // module-constant — rebuilding them would change every cell component's
  // identity and remount (blurring) all inputs on each grid render.
  const meta: GridCellContext = {
    readOnly,
    jobs: jobsQuery.data?.jobs ?? [],
    jobsLoading: jobsQuery.isPending,
    patchLine,
    updateDraft: draftRows.updateDraft,
    isPhantom: draftRows.isPhantom,
    isPersisting: draftRows.isPersisting,
    isFailed: draftRows.isFailed,
  }

  const table = useTable({
    features: editableGridFeatures,
    data: rows,
    columns: COLUMNS,
    getRowId: (row) => (row.type === 'server' ? row.line.id : row.localId),
    meta: { poGrid: meta },
  })

  return (
    <DataTable
      table={table}
      editableColumns={EDITABLE_COLUMNS}
      draftLocalId={(row) => (row.type === 'draft' ? row.localId : null)}
      rowExitHandlers={draftRows.rowExitHandlers}
    />
  )
}

const EDITABLE_COLUMNS = new Set(['description', 'job', 'quantity', 'unit_cost'])

type CellProps = CellContext<typeof editableGridFeatures, GridRow>

function cellMeta(table: Table<typeof editableGridFeatures, GridRow>): GridCellContext {
  const meta = table.options.meta?.poGrid
  if (!meta) throw new Error('PoLinesTable is missing its meta context')
  return meta
}

/** The line fields an item pick writes (v1 parity: the stock row wins). */
function stockPickFields(stock: StockItem): PoLinePatch & Partial<PurchaseOrderLineOut> {
  return {
    description: stock.description,
    unit_cost: stock.unit_cost,
    item_code: stock.item_code,
    metal_type: stock.metal_type,
    alloy: stock.alloy,
    specifics: stock.specifics,
    location: stock.location,
  }
}

function ItemCell({ row, table }: CellProps) {
  const rowIndex = row.index
  const context = cellMeta(table)
  const gridRow = row.original
  const itemCode = gridRow.type === 'server' ? gridRow.line.item_code : gridRow.draft.item_code
  const description =
    gridRow.type === 'server' ? gridRow.line.description : gridRow.draft.description

  return (
    <ItemSelect
      wrapperAutomationId={`PoLinesTable-item-${rowIndex}`}
      label={poLineItemLabel(itemCode, description)}
      disabled={rowLocked(context, gridRow)}
      allowLabour={false}
      onPickStock={(stock) => {
        if (gridRow.type === 'server') {
          const fields = stockPickFields(stock)
          context.patchLine(gridRow.line.id, fields, fields)
          return
        }
        // No persist: typed rows POST on row EXIT only, so an early create
        // response can never race the quantity still being typed.
        context.updateDraft(gridRow.localId, stockPickFields(stock))
      }}
    />
  )
}

function DescriptionCell({ row, table }: CellProps) {
  const rowIndex = row.index
  const context = cellMeta(table)
  const gridRow = row.original
  const serverValue =
    gridRow.type === 'server' ? gridRow.line.description : gridRow.draft.description
  const field = useAutosaveField(
    serverValue,
    (value) => {
      if (gridRow.type === 'server') {
        context.patchLine(gridRow.line.id, { description: value }, { description: value })
      } else {
        context.updateDraft(gridRow.localId, { description: value })
      }
    },
    undefined,
    gridRow.type === 'server',
  )

  return (
    <span className="inline-flex items-center gap-1">
      <input
        type="text"
        value={field.value}
        disabled={rowLocked(context, gridRow)}
        data-automation-id={`PoLinesTable-description-${rowIndex}`}
        aria-label={`Description row ${rowIndex}`}
        className="w-56 rounded border border-slate-200 px-2 py-1"
        onChange={(event) => field.onChange(event.target.value)}
        onFocus={field.onFocus}
        onBlur={field.onBlur}
      />
      {gridRow.type === 'draft' && context.isFailed(gridRow.localId) && <SaveFailedBadge />}
    </span>
  )
}

function JobCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const jobNumber = gridRow.type === 'server' ? gridRow.line.job_number : gridRow.draft.job_number
  const jobName = gridRow.type === 'server' ? gridRow.line.job_name : gridRow.draft.job_name

  return (
    <JobSelect
      jobNumber={jobNumber}
      jobName={jobName}
      jobs={context.jobs}
      jobsLoading={context.jobsLoading}
      disabled={rowLocked(context, gridRow)}
      onPickJob={(job) => {
        if (gridRow.type === 'server') {
          context.patchLine(
            gridRow.line.id,
            { job_id: job.id },
            { job_id: job.id, job_number: job.job_number, job_name: job.name },
          )
          return
        }
        context.updateDraft(gridRow.localId, {
          job_id: job.id,
          job_number: job.job_number,
          job_name: job.name,
        })
      }}
    />
  )
}

function NumberCell({
  row,
  table,
  field: fieldName,
  automation,
}: CellProps & {
  field: 'quantity' | 'unit_cost'
  automation: string
}) {
  const rowIndex = row.index
  const context = cellMeta(table)
  const gridRow = row.original
  const raw = gridRow.type === 'server' ? gridRow.line[fieldName] : gridRow.draft[fieldName]
  const serverValue = raw === null ? '' : trimDecimal(raw)

  const field = useAutosaveField(
    serverValue,
    (value) => {
      if (gridRow.type === 'server') {
        context.patchLine(gridRow.line.id, { [fieldName]: value }, { [fieldName]: value })
      } else {
        context.updateDraft(gridRow.localId, { [fieldName]: value })
      }
    },
    parseDecimalInput,
    gridRow.type === 'server',
  )

  return (
    <input
      type="number"
      inputMode="decimal"
      step={fieldName === 'quantity' ? 1 : 0.01}
      value={field.value}
      disabled={rowLocked(context, gridRow)}
      data-automation-id={`PoLinesTable-${automation}-${rowIndex}`}
      aria-label={`${automation} row ${rowIndex}`}
      className="w-24 rounded border border-slate-200 px-2 py-1 text-right tabular-nums disabled:bg-slate-50 disabled:text-slate-500"
      onChange={(event) => field.onChange(event.target.value)}
      onFocus={field.onFocus}
      onBlur={field.onBlur}
    />
  )
}

function TotalCell({ row }: CellProps) {
  const gridRow = row.original
  const quantity = gridRow.type === 'server' ? gridRow.line.quantity : gridRow.draft.quantity
  const unitCost = gridRow.type === 'server' ? gridRow.line.unit_cost : gridRow.draft.unit_cost
  if (unitCost === null) {
    return <span className="text-slate-400">—</span>
  }
  const total = Number(quantity) * Number(unitCost)
  if (!Number.isFinite(total)) {
    return <span className="text-slate-400">—</span>
  }
  return <span className="tabular-nums">{formatCurrency(total)}</span>
}

const columnHelper = createColumnHelper<typeof editableGridFeatures, GridRow>()

// Column order is load-bearing: unit_cost must be the LAST focusable cell in
// a row so the wire contract's Tab out of it exits the row and fires the
// draft commit (total renders no input; there is no actions column).
const COLUMNS = [
  columnHelper.display({ id: 'item', header: 'Item', cell: ItemCell }),
  columnHelper.display({ id: 'description', header: 'Description', cell: DescriptionCell }),
  columnHelper.display({ id: 'job', header: 'Job', cell: JobCell }),
  columnHelper.display({
    id: 'quantity',
    header: 'Quantity',
    cell: (props: CellProps) => <NumberCell {...props} field="quantity" automation="quantity" />,
  }),
  columnHelper.display({
    id: 'unit_cost',
    header: 'Unit Cost',
    cell: (props: CellProps) => <NumberCell {...props} field="unit_cost" automation="unit-cost" />,
  }),
  columnHelper.display({ id: 'total', header: 'Total', cell: TotalCell }),
]
