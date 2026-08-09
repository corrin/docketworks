import { useMemo, useRef, useState } from 'react'
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
  isDraftReadyToPersist,
  labourPickPatch,
  parseDecimalInput,
  stockPickPatch,
} from './calc'
import { ItemSelect } from './ItemSelect'
import { emptyDraft, type CostSetKind, type DraftLine, type GridRow } from './types'
import { useAutosaveField } from './useAutosaveField'
import { useCostLines } from './useCostLines'

const KIND_LABELS: Record<string, string> = {
  time: 'Labour',
  material: 'Material',
  adjust: 'Adjustment',
}

interface DraftRow {
  localId: string
  draft: DraftLine
}

function freshPhantom(): DraftRow {
  return { localId: crypto.randomUUID(), draft: emptyDraft() }
}

function draftIsEmpty(draft: DraftLine): boolean {
  return (
    draft.desc.trim() === '' &&
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
  readOnly: boolean
  materialsMarkup: string
  wageRate: string
  patchLine: (lineId: string, body: CostLineUpdateRequest) => void
  updateDraft: (localId: string, patch: Partial<DraftLine>) => void
  commitDraftField: (localId: string) => void
  removeDraft: (localId: string) => void
  deleteLine: (lineId: string) => void
  isPhantom: (localId: string) => boolean
}

declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface TableMeta<TData> extends GridCellContext {}
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
  const { costSetQuery, patchLine, createLine, deleteLine } = useCostLines(jobId, kind)
  const [drafts, setDrafts] = useState<DraftRow[]>([freshPhantom()])
  const persistingRef = useRef<Set<string>>(new Set())

  const serverLines = useMemo(
    () => costSetQuery.data?.cost_lines ?? [],
    [costSetQuery.data?.cost_lines],
  )

  const rows = useMemo<GridRow[]>(
    () => [
      ...serverLines.map((line): GridRow => ({ type: 'server', line })),
      ...drafts.map((entry): GridRow => ({ type: 'draft', ...entry })),
    ],
    [serverLines, drafts],
  )

  const persistDraftIfReady = (currentDrafts: DraftRow[], localId: string) => {
    const entry = currentDrafts.find((candidate) => candidate.localId === localId)
    if (!entry) return
    if (!isDraftReadyToPersist(entry.draft)) return
    if (persistingRef.current.has(localId)) return
    persistingRef.current.add(localId)
    const { draft } = entry
    createLine(
      {
        kind: draft.kind,
        desc: draft.desc,
        quantity: draft.quantity,
        unit_cost: draft.unit_cost ?? undefined,
        unit_rev: draft.unit_rev ?? undefined,
        ext_refs: draft.ext_refs,
        labour_subtype: draft.kind === 'time' ? draft.labour_subtype : undefined,
        accounting_date: localIsoDate(),
      },
      () => {
        persistingRef.current.delete(localId)
        setDrafts((current) => {
          const remaining = current.filter((candidate) => candidate.localId !== localId)
          return remaining.length ? remaining : [freshPhantom()]
        })
      },
    )
  }

  // Fresh every render so handlers close over current state; passed as table
  // meta, which cells read at render/event time. The COLUMN definitions stay
  // module-constant — rebuilding them would change every cell component's
  // identity and remount (blurring) all inputs on each grid render.
  const meta: GridCellContext = {
    jobId,
    readOnly,
    materialsMarkup,
    wageRate,
    patchLine,
    deleteLine,
    isPhantom: (localId) => drafts.at(-1)?.localId === localId,
    updateDraft: (localId, patch) => {
      setDrafts((current) => {
        const next = current.map((entry) =>
          entry.localId === localId ? { ...entry, draft: { ...entry.draft, ...patch } } : entry,
        )
        // Invariant: exactly one trailing empty phantom. The moment the
        // phantom stops being empty it becomes an ordinary draft and a fresh
        // phantom is appended behind it.
        const last = next.at(-1)
        if (last && !draftIsEmpty(last.draft)) {
          next.push(freshPhantom())
        }
        return next
      })
    },
    commitDraftField: (localId) => {
      // Inside the updater so it observes the same render's updateDraft; the
      // persisting-set guard makes StrictMode's double invocation harmless.
      setDrafts((current) => {
        persistDraftIfReady(current, localId)
        return current
      })
    },
    removeDraft: (localId) => {
      setDrafts((current) => {
        const remaining = current.filter((entry) => entry.localId !== localId)
        return remaining.length ? remaining : [freshPhantom()]
      })
    },
  }

  const table = useReactTable({
    data: rows,
    columns: COLUMNS,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => (row.type === 'server' ? row.line.id : row.localId),
    meta,
  })

  if (costSetQuery.isPending) {
    return <p className="p-4 text-sm text-slate-500">Loading cost lines…</p>
  }
  if (costSetQuery.isError) {
    // No fabricated empty grid: a failed load must not read as a job with no
    // cost lines.
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
          {table.getRowModel().rows.map((row, rowIndex) => (
            <tr
              key={row.id}
              data-automation-id={`DataTable-row-${rowIndex}`}
              data-row-id={row.id}
              className="border-b border-slate-100 align-top hover:bg-slate-50"
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
          ))}
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
  const meta = table.options.meta
  if (!meta) throw new Error('CostLineGrid table is missing its meta context')
  return meta
}

function KindCell({ row }: CellProps) {
  const kind = row.original.type === 'server' ? row.original.line.kind : row.original.draft.kind
  return (
    <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
      {KIND_LABELS[kind] ?? kind}
    </span>
  )
}

function DescCell({ row, table }: CellProps) {
  const rowIndex = row.index
  const context = cellMeta(table)
  const gridRow = row.original
  const serverValue = gridRow.type === 'server' ? (gridRow.line.desc ?? '') : gridRow.draft.desc
  const field = useAutosaveField(serverValue, (value) => {
    if (gridRow.type === 'server') {
      // ADR 0040: blank clears to null, never an empty string.
      context.patchLine(gridRow.line.id, { desc: value.trim() === '' ? null : value })
    } else {
      context.updateDraft(gridRow.localId, { desc: value })
      context.commitDraftField(gridRow.localId)
    }
  })

  return (
    <textarea
      rows={1}
      value={field.value}
      disabled={context.readOnly}
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
  // Time lines price from the wage/charge-out rates, not by hand.
  const editable = fieldName === 'quantity' || kind !== 'time'

  const serverValue =
    gridRow.type === 'server' ? gridRow.line[fieldName] : (gridRow.draft[fieldName] ?? '')

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
        context.updateDraft(gridRow.localId, { [fieldName]: value })
        context.commitDraftField(gridRow.localId)
      }
    },
    parseDecimalInput,
  )

  const step = fieldName !== 'quantity' ? 0.01 : kind === 'time' ? 0.25 : 1
  return (
    <input
      type="number"
      inputMode="decimal"
      step={step}
      value={field.value}
      disabled={context.readOnly || !editable}
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
        disabled={context.readOnly}
        onPickStock={(stock: StockItem) => {
          const patch = stockPickPatch(draftAsLine, stock, context.materialsMarkup)
          context.updateDraft(gridRow.localId, {
            kind: 'material',
            desc: patch.desc ?? '',
            unit_cost: String(patch.unit_cost ?? ''),
            unit_rev: String(patch.unit_rev ?? ''),
            ext_refs: patch.ext_refs ?? {},
          })
          context.commitDraftField(gridRow.localId)
        }}
        onPickLabour={(rate: JobLabourRateOut) => {
          context.updateDraft(gridRow.localId, {
            kind: 'time',
            labour_subtype: rate.labour_subtype,
            desc: rate.labour_subtype_name,
            unit_cost: context.wageRate,
            unit_rev: rate.charge_out_rate,
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
      disabled={context.readOnly}
      onPickStock={(stock: StockItem) =>
        context.patchLine(line.id, stockPickPatch(line, stock, context.materialsMarkup))
      }
      onPickLabour={(rate: JobLabourRateOut) =>
        context.patchLine(line.id, labourPickPatch(line, { rate, wageRate: context.wageRate }))
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
      disabled={context.readOnly || isEmptyPhantom}
      aria-label="Delete line"
      data-automation-id={`SmartCostLinesTable-delete-${rowIndex}`}
      onClick={() => {
        if (gridRow.type === 'draft') {
          context.removeDraft(gridRow.localId)
          return
        }
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
