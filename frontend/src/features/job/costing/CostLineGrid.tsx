import { useMemo } from 'react'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  type CellContext,
  type Table,
} from '@tanstack/react-table'
import { Trash2 } from 'lucide-react'

import type { CostLineOut, CostLineUpdateRequest, JobLabourRateOut, StockItem } from '@/api'
import { Button } from '@/components/ui/button'
import { formatCurrency, formatDate, localIsoDate } from '@/lib/format'
import {
  derivedUnitRev,
  isDeliveryReceiptLine,
  isDraftReadyToPersist,
  labourPickDesc,
  labourPickPatch,
  parseDecimalInput,
  stockPickPatch,
  trimDecimal,
} from './calc'
import { ItemSelect } from './ItemSelect'
import { emptyDraft, type CostSetKind, type DraftLine, type GridRow } from './types'
import { useAutosaveField } from '@/features/shared/useAutosaveField'
import { useDraftRows } from '@/features/shared/useDraftRows'
import { useCostLines } from './useCostLines'

const KIND_LABELS: Record<string, string> = {
  time: 'Labour',
  material: 'Material',
  adjust: 'Adjustment',
}

function draftIsEmpty(draft: DraftLine): boolean {
  return (
    draft.desc.trim() === '' &&
    draft.quantity === '1' &&
    draft.unit_cost === null &&
    draft.unit_rev === null &&
    draft.labour_subtype === null &&
    !('stock_id' in draft.ext_refs)
  )
}

interface CostLineGridProps {
  jobId: string
  kind: CostSetKind
  /** CompanyDefaults.materials_markup as the wire string, e.g. "0.2000". */
  materialsMarkup: string
  /** CompanyDefaults.wage_rate as the wire string. */
  wageRate: string
  readOnly?: boolean
}

interface GridCellContext {
  jobId: string
  kind: CostSetKind
  readOnly: boolean
  materialsMarkup: string
  wageRate: string
  patchLine: (lineId: string, body: CostLineUpdateRequest) => void
  updateDraft: (localId: string, patch: Partial<DraftLine>) => void
  commitDraftField: (localId: string) => void
  removeDraft: (localId: string) => void
  deleteLine: (lineId: string) => void
  consumeDraft: (localId: string, stockId: string) => void
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
  // in the app, so a flat extension here would force the timesheet grid's
  // meta to satisfy this grid's context and vice versa.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface TableMeta<TData> {
    costGrid?: GridCellContext
  }
}

/**
 * The one cost-line grid (estimate, quote and actual are prop configs of it).
 * The selector contract is load-bearing for the E2E suite:
 * `.smart-costlines-table` on the table, tbody holds data rows plus exactly
 * one trailing empty phantom row and NOTHING else (loading/error render
 * outside; totals live in the summary card, not a tfoot), and the
 * SmartCostLinesTable-* / DataTable-row-* / data-grid-* attributes are
 * derived from the visual row index at render time.
 */
export function CostLineGrid({
  jobId,
  kind,
  materialsMarkup,
  wageRate,
  readOnly = false,
}: CostLineGridProps) {
  const { costSetQuery, patchLine, createLine, deleteLine, consumeStockLine } = useCostLines(
    jobId,
    kind,
  )
  const draftRows = useDraftRows<DraftLine>({
    emptyDraft,
    draftIsEmpty,
    isReady: isDraftReadyToPersist,
    persist: (draft, callbacks) => {
      // An untouched revenue derives from the cost HERE, not on the cost
      // commit: writing it into the draft state mid-edit flips the controlled
      // unit-rev input under a concurrent override, which then loses.
      const unitRev =
        draft.unit_rev ??
        (draft.kind !== 'time' && draft.unit_cost !== null
          ? derivedUnitRev(draft.unit_cost, materialsMarkup)
          : undefined)
      createLine(
        {
          kind: draft.kind,
          desc: draft.desc,
          quantity: draft.quantity,
          unit_cost: draft.unit_cost ?? undefined,
          unit_rev: unitRev,
          ext_refs: draft.ext_refs,
          labour_subtype: draft.kind === 'time' ? draft.labour_subtype : undefined,
          accounting_date: localIsoDate(),
        },
        callbacks,
      )
    },
  })

  const serverLines = useMemo(
    () => costSetQuery.data?.cost_lines ?? [],
    [costSetQuery.data?.cost_lines],
  )

  const rows = useMemo<GridRow[]>(
    () => [
      ...serverLines.map((line): GridRow => ({ type: 'server', line })),
      ...draftRows.drafts.map((entry): GridRow => ({ type: 'draft', ...entry })),
    ],
    [serverLines, draftRows.drafts],
  )

  // Fresh every render so handlers close over current state; passed as table
  // meta, which cells read at render/event time. The COLUMN definitions stay
  // module-constant — rebuilding them would change every cell component's
  // identity and remount (blurring) all inputs on each grid render.
  const meta: GridCellContext = {
    jobId,
    kind,
    readOnly,
    materialsMarkup,
    wageRate,
    patchLine,
    deleteLine,
    isPhantom: draftRows.isPhantom,
    isPersisting: draftRows.isPersisting,
    isFailed: draftRows.isFailed,
    consumeDraft: (localId, stockId) => {
      // The guard goes up BEFORE the request and the pending row-exit timer
      // dies: focus leaving the row after the pick must not also POST the
      // typed draft as an adjustment beside the consumed line.
      const draft = draftRows.beginExternalPersist(localId)
      if (draft === null) return
      consumeStockLine(stockId, draft.quantity, {
        onCreated: () => draftRows.settleExternalPersist(localId, 'created'),
        onFailed: () => draftRows.settleExternalPersist(localId, 'failed'),
      })
    },
    updateDraft: draftRows.updateDraft,
    commitDraftField: draftRows.commitDraft,
    removeDraft: draftRows.removeDraft,
  }

  const table = useReactTable({
    data: rows,
    columns: COLUMNS,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => (row.type === 'server' ? row.line.id : row.localId),
    meta: { costGrid: meta },
  })

  if (costSetQuery.isPending) {
    return <p className="p-4 text-sm text-slate-500">Loading cost lines…</p>
  }
  if (costSetQuery.isError && costSetQuery.data === undefined) {
    // No fabricated empty grid: a failed FIRST load must not read as a job
    // with no cost lines. An errored background refetch keeps the working
    // grid (and any unsaved drafts) — the write paths toast their own
    // failures.
    return (
      <p className="p-4 text-sm font-medium text-red-700">
        Could not load the cost lines. Reload the page.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="smart-costlines-table min-w-full text-sm">
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
            // A const, so the ternary's narrowing survives into the closure.
            const original = row.original
            return (
              <tr
                key={row.id}
                data-automation-id={`DataTable-row-${rowIndex}`}
                data-row-id={row.id}
                className="border-b border-slate-100 align-top hover:bg-slate-50"
                // Focus leaving the whole ROW is the create gesture for typed
                // drafts (item picks persist on their own) — the deferred
                // commit and its cancellation live in useDraftRows.
                {...(original.type === 'draft' ? draftRows.rowExitHandlers(original.localId) : {})}
              >
                {row.getVisibleCells().map((cell) => {
                  const columnId = cell.column.id
                  const editable = EDITABLE_COLUMNS.has(columnId)
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

const EDITABLE_COLUMNS = new Set(['desc', 'quantity', 'unit_cost', 'unit_rev'])

// The visual row index is row.index: the grid uses the core row model with
// no sorting or filtering, so data order IS visual order. Automation ids must
// track it at render time, never a memoised copy.
type CellProps = CellContext<GridRow, unknown>

function cellMeta(table: Table<GridRow>): GridCellContext {
  const meta = table.options.meta?.costGrid
  if (!meta) throw new Error('CostLineGrid table is missing its meta context')
  return meta
}

function KindCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const kind = gridRow.type === 'server' ? gridRow.line.kind : gridRow.draft.kind
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
        {KIND_LABELS[kind] ?? kind}
      </span>
      {gridRow.type === 'draft' && context.isFailed(gridRow.localId) && (
        <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
          Save failed
        </span>
      )}
    </span>
  )
}

function DescCell({ row, table }: CellProps) {
  const rowIndex = row.index
  const context = cellMeta(table)
  const gridRow = row.original
  const serverValue = gridRow.type === 'server' ? (gridRow.line.desc ?? '') : gridRow.draft.desc
  const field = useAutosaveField(
    serverValue,
    (value) => {
      if (gridRow.type === 'server') {
        // ADR 0040: blank clears to null, never an empty string.
        context.patchLine(gridRow.line.id, { desc: value.trim() === '' ? null : value })
      } else {
        const patch: Partial<DraftLine> = { desc: value }
        // A typed free-form row is an adjustment (v1 rule): material means
        // a stock pick, time a labour pick — both set kind themselves.
        if (!('stock_id' in gridRow.draft.ext_refs) && gridRow.draft.labour_subtype === null) {
          patch.kind = 'adjust'
        }
        // No persist here: typed rows POST on row EXIT only, so tabbing
        // across cells can never race an early create response (v1 rule).
        context.updateDraft(gridRow.localId, patch)
      }
    },
    undefined,
    gridRow.type === 'server',
  )

  // A timesheet line's description is edited in the timesheet UI only, and
  // a delivery-receipt allocation is not edited here at all (v1 rule).
  const timesheetLocked =
    context.kind === 'actual' && gridRow.type === 'server' && gridRow.line.kind === 'time'
  const receiptLocked = gridRow.type === 'server' && isDeliveryReceiptLine(gridRow.line)

  return (
    <textarea
      rows={1}
      value={field.value}
      disabled={rowLocked(context, gridRow) || timesheetLocked || receiptLocked}
      aria-label={`Description row ${rowIndex}`}
      className="w-48 resize-y rounded border border-slate-200 px-2 py-1"
      onChange={(event) => field.onChange(event.target.value)}
      onFocus={field.onFocus}
      onBlur={field.onBlur}
    />
  )
}

function NumberCell({
  row,
  table,
  field: fieldName,
  automation,
}: CellProps & {
  field: 'quantity' | 'unit_cost' | 'unit_rev'
  automation: string
}) {
  const rowIndex = row.index
  const context = cellMeta(table)
  const gridRow = row.original
  const kind = gridRow.type === 'server' ? gridRow.line.kind : gridRow.draft.kind
  // Time lines price from the wage/charge-out rates, not by hand; on the
  // actual set a persisted timesheet line locks entirely (edited in the
  // timesheet UI only). Delivery-receipt allocations lock everywhere (v1
  // rule — their quantity is purchasing history). Everything else keeps
  // inline editing, consumed materials included (v1 allowed repricing).
  const timesheetLocked = context.kind === 'actual' && gridRow.type === 'server' && kind === 'time'
  const receiptLocked = gridRow.type === 'server' && isDeliveryReceiptLine(gridRow.line)
  const editable =
    !timesheetLocked && !receiptLocked && (fieldName === 'quantity' || kind !== 'time')

  // Trimmed for display: the wire carries Decimal strings ('3.000'), and the
  // E2E specs assert typed values round-trip as typed ('3').
  const serverValue = trimDecimal(
    gridRow.type === 'server' ? gridRow.line[fieldName] : (gridRow.draft[fieldName] ?? ''),
  )

  const field = useAutosaveField(
    serverValue,
    (value) => {
      if (gridRow.type === 'server') {
        const body: CostLineUpdateRequest = { [fieldName]: value }
        // Editing a material/adjustment cost re-derives the default revenue
        // (manual override bookkeeping is deferred past this slice).
        if (fieldName === 'unit_cost' && kind !== 'time') {
          body.unit_rev = derivedUnitRev(value, context.materialsMarkup)
        }
        context.patchLine(gridRow.line.id, body)
      } else {
        // No derivation here: an untouched unit_rev derives at POST time.
        // Writing the derived value into the draft on the cost commit flips
        // the controlled unit-rev input mid-edit and loses an override.
        // No persist either: typed rows POST on row EXIT only (v1 rule).
        context.updateDraft(gridRow.localId, { [fieldName]: value })
      }
    },
    parseDecimalInput,
    gridRow.type === 'server',
  )

  const step = fieldName !== 'quantity' ? 0.01 : kind === 'time' ? 0.25 : 1
  return (
    <input
      type="number"
      inputMode="decimal"
      step={step}
      value={field.value}
      disabled={rowLocked(context, gridRow) || !editable}
      data-automation-id={`SmartCostLinesTable-${automation}-${rowIndex}`}
      aria-label={`${automation} row ${rowIndex}`}
      className="w-24 rounded border border-slate-200 px-2 py-1 text-right tabular-nums disabled:bg-slate-50 disabled:text-slate-500"
      onChange={(event) => field.onChange(event.target.value)}
      onFocus={field.onFocus}
      onBlur={field.onBlur}
    />
  )
}

function ItemCell({ row, table }: CellProps) {
  const rowIndex = row.index
  const context = cellMeta(table)
  const gridRow = row.original

  if (gridRow.type === 'draft') {
    // Draft rows keep the same trigger contract; picking completes the draft.
    const draftAsLine: CostLineOut = {
      ...EMPTY_SERVER_SHAPE,
      desc: gridRow.draft.desc,
      kind: gridRow.draft.kind,
      labour_subtype: gridRow.draft.labour_subtype,
      ext_refs: gridRow.draft.ext_refs,
    }
    return (
      <ItemSelect
        jobId={context.jobId}
        line={draftAsLine}
        rowIndex={rowIndex}
        disabled={rowLocked(context, gridRow)}
        allowLabour={context.kind !== 'actual'}
        onPickStock={(stock: StockItem) => {
          if (context.kind === 'actual') {
            // Actual materials are booked by consuming stock: the SERVER
            // creates the line (stock description and pricing win over
            // anything typed), so no draft patch and no cost-line POST.
            context.consumeDraft(gridRow.localId, stock.id)
            return
          }
          const patch = stockPickPatch(draftAsLine, stock, context.materialsMarkup)
          context.updateDraft(gridRow.localId, {
            kind: 'material',
            desc: patch.desc ?? '',
            // Preserve absence as null — '' would satisfy the ready check
            // and persist a partial row.
            unit_cost: typeof patch.unit_cost === 'string' ? patch.unit_cost : null,
            unit_rev: typeof patch.unit_rev === 'string' ? patch.unit_rev : null,
            labour_subtype: null,
            ext_refs: patch.ext_refs ?? {},
          })
          context.commitDraftField(gridRow.localId)
        }}
        onPickLabour={(rate: JobLabourRateOut, allRates: readonly JobLabourRateOut[]) => {
          // Same rules as the server-row patch: keep a user-authored desc,
          // and drop any stale stock binding from a failed material pick.
          const { stock_id: _dropped, ...keptRefs } = gridRow.draft.ext_refs
          context.updateDraft(gridRow.localId, {
            kind: 'time',
            labour_subtype: rate.labour_subtype,
            desc: labourPickDesc(gridRow.draft.desc, rate, allRates),
            unit_cost: context.wageRate,
            unit_rev: rate.charge_out_rate,
            ext_refs: keptRefs,
          })
          context.commitDraftField(gridRow.localId)
        }}
      />
    )
  }

  const line = gridRow.line
  return (
    <ItemSelect
      jobId={context.jobId}
      line={line}
      rowIndex={rowIndex}
      // Booking on the actual set is consume-only, so a persisted row's
      // trigger is dead there (v1 locked stock lines; v2 extends it to
      // adjust rows): a repick would rewrite the consume-derived binding
      // through a plain PATCH and desync the stock ledger (the drawn-down
      // item keeps its shortfall; the new one gets returns it never lost).
      // Delivery-receipt allocations are never re-bound anywhere (v1 rule).
      disabled={context.readOnly || context.kind === 'actual' || isDeliveryReceiptLine(line)}
      allowLabour={context.kind !== 'actual'}
      // A timesheet line's subtype is edited in the timesheet UI only.
      textOnly={context.kind === 'actual' && line.kind === 'time'}
      onPickStock={(stock: StockItem) =>
        context.patchLine(line.id, stockPickPatch(line, stock, context.materialsMarkup))
      }
      onPickLabour={(rate: JobLabourRateOut, allRates: readonly JobLabourRateOut[]) =>
        context.patchLine(
          line.id,
          labourPickPatch(line, { rate, wageRate: context.wageRate, allRates }),
        )
      }
    />
  )
}

function TotalCell({ row, field }: CellProps & { field: 'total_cost' | 'total_rev' }) {
  if (row.original.type !== 'server') {
    return <span className="text-slate-400">—</span>
  }
  return <span className="tabular-nums">{formatCurrency(row.original.line[field])}</span>
}

function DateCell({ row }: CellProps) {
  if (row.original.type !== 'server') {
    return <span className="text-slate-400">—</span>
  }
  return (
    <span className="whitespace-nowrap text-slate-600">
      {formatDate(row.original.line.accounting_date)}
    </span>
  )
}

function ActionsCell({ row, table }: CellProps) {
  const rowIndex = row.index
  const context = cellMeta(table)
  const gridRow = row.original
  const isEmptyPhantom = gridRow.type === 'draft' && context.isPhantom(gridRow.localId)

  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={rowLocked(context, gridRow) || isEmptyPhantom}
      aria-label="Delete line"
      data-automation-id={`SmartCostLinesTable-delete-${rowIndex}`}
      onPointerDown={
        gridRow.type === 'draft'
          ? (event) => {
              // Primary press only: pointerdown also fires for right/middle
              // clicks, which must not delete anything.
              if (event.button !== 0) return
              // pointerdown, not click: browsers that don't focus buttons on
              // click (Safari) fire the input's blur with relatedTarget null
              // first — the row-exit commit would CREATE the draft the user
              // is deleting. Removing on pointerdown wins that race.
              context.removeDraft(gridRow.localId)
            }
          : undefined
      }
      onClick={() => {
        if (gridRow.type === 'draft') return
        if (!window.confirm('Delete this cost line?')) return
        context.deleteLine(gridRow.line.id)
      }}
    >
      <Trash2 className="h-4 w-4 text-slate-500" />
    </Button>
  )
}

const columnHelper = createColumnHelper<GridRow>()

// Module-constant on purpose: rebuilding column defs per render would give
// every cell renderer a new component identity, remounting (and blurring)
// every input on each grid render. Cells reach live state via table meta.
const COLUMNS = [
  columnHelper.display({ id: 'kind', header: 'Type', cell: KindCell }),
  columnHelper.display({ id: 'item', header: 'Item', cell: ItemCell }),
  columnHelper.display({ id: 'desc', header: 'Description', cell: DescCell }),
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
  columnHelper.display({
    id: 'unit_rev',
    header: 'Unit Rev',
    cell: (props: CellProps) => <NumberCell {...props} field="unit_rev" automation="unit-rev" />,
  }),
  columnHelper.display({
    id: 'total_cost',
    header: 'Total Cost',
    cell: (props: CellProps) => <TotalCell {...props} field="total_cost" />,
  }),
  columnHelper.display({
    id: 'total_rev',
    header: 'Total Revenue',
    cell: (props: CellProps) => <TotalCell {...props} field="total_rev" />,
  }),
  columnHelper.display({ id: 'accounting_date', header: 'Date', cell: DateCell }),
  columnHelper.display({ id: 'actions', header: 'Actions', cell: ActionsCell }),
]

// A minimal CostLineOut-shaped value so draft rows can share ItemSelect and
// the pick patch helpers with server rows.
const EMPTY_SERVER_SHAPE: CostLineOut = {
  accounting_date: '',
  approved: false,
  created_at: '',
  desc: null,
  entry_seq: null,
  ext_refs: {},
  id: '',
  kind: 'material',
  labour_subtype: null,
  meta: {},
  quantity: '1',
  staff: null,
  total_cost: 0,
  total_rev: 0,
  unit_cost: '0',
  unit_rev: '0',
  updated_at: '',
  xero_expense_id: null,
  xero_last_modified: null,
  xero_last_synced: null,
  xero_pay_item: null,
  xero_time_id: null,
}
