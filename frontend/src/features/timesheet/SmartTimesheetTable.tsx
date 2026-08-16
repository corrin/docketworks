import { useEffect, useMemo, useState } from 'react'
import {
  useTable,
  type CellContext,
  type ColumnDef,
  type RowData,
  type Table,
  type TableFeatures,
} from '@tanstack/react-table'
import { Check, Trash2 } from 'lucide-react'

import type {
  CostLineUpdateRequest,
  TimesheetCostLineOut,
  TimesheetJobOut,
  XeroPayItemOut,
} from '@/api'
import { formatCurrency } from '@/lib/format'
import { DataTable } from '@/features/shared/DataTable'
import { editableGridFeatures } from '@/features/shared/editableGridTable'
import { SaveFailedBadge } from '@/features/shared/SaveFailedBadge'
import { useAutosaveField } from '@/features/shared/useAutosaveField'
import { useDraftRows } from '@/features/shared/useDraftRows'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { formatHoursDisplay, parseHoursInput } from './hours'
import { rateForSubtype, subtypeName } from './labourRates'
import { lineBillMultiplier, lineIsBillable, lineMeta, lineWageMultiplier } from './lineMeta'
import { TimesheetJobPicker } from './TimesheetJobPicker'
import {
  applyJobPick,
  draftIsEmpty,
  draftIsReady,
  emptyTimesheetDraft,
  type TimesheetDraft,
} from './timesheetDraft'
import type { TimesheetCreateBody } from './useTimesheetEntries'

type TimesheetGridRow =
  | { type: 'server'; line: TimesheetCostLineOut }
  | { type: 'draft'; localId: string; draft: TimesheetDraft }

interface CreateEntryCallbacks {
  onCreated: (line: TimesheetCostLineOut) => void
  onFailed: () => void
}

export interface SmartTimesheetTableProps {
  entries: readonly TimesheetCostLineOut[]
  jobs: readonly TimesheetJobOut[]
  payItems: readonly XeroPayItemOut[]
  staffId: string
  date: string
  /** The staff member's loaded hourly rate (drafts price hours × this). */
  staffWageRate: number
  patchLine: (lineId: string, body: CostLineUpdateRequest) => void
  createLine: (job: TimesheetJobOut, body: TimesheetCreateBody, cb: CreateEntryCallbacks) => void
  deleteLine: (lineId: string) => void
  approveLine: (lineId: string) => void
}

interface TimesheetCellContext {
  jobs: readonly TimesheetJobOut[]
  payItems: readonly XeroPayItemOut[]
  staffWageRate: number
  patchLine: SmartTimesheetTableProps['patchLine']
  deleteLine: SmartTimesheetTableProps['deleteLine']
  approveLine: SmartTimesheetTableProps['approveLine']
  updateDraft: (localId: string, patch: Partial<TimesheetDraft>) => void
  commitDraft: (localId: string) => void
  removeDraft: (localId: string) => void
  isPhantom: (localId: string) => boolean
  isPersisting: (localId: string) => boolean
  anyPersisting: boolean
  isFailed: (localId: string) => boolean
}

declare module '@tanstack/react-table' {
  // Namespaced for the same reason as CostLineGrid's costGrid key.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface TableMeta<TFeatures extends TableFeatures, TData extends RowData> {
    timesheetGrid?: TimesheetCellContext
  }
}

function cellMeta(
  table: Table<typeof editableGridFeatures, TimesheetGridRow>,
): TimesheetCellContext {
  const meta = table.options.meta?.timesheetGrid
  if (!meta) throw new Error('SmartTimesheetTable is missing its meta context')
  return meta
}

function jobForRow(
  context: TimesheetCellContext,
  gridRow: TimesheetGridRow,
): TimesheetJobOut | null {
  if (gridRow.type === 'draft') return gridRow.draft.job
  return context.jobs.find((job) => job.id === gridRow.line.job_id) ?? null
}

// ── Rate select options ──────────────────────────────────────────────────

const RATE_OPTIONS = [
  { value: '1', label: 'Ord', multiplier: 1.0 },
  { value: '1.5', label: '1.5x', multiplier: 1.5 },
  { value: '2', label: '2.0x', multiplier: 2.0 },
  { value: '0', label: 'Unpaid', multiplier: 0.0 },
] as const

function rateValue(multiplier: number): string {
  const option = RATE_OPTIONS.find(
    (candidate) => Math.abs(candidate.multiplier - multiplier) < 0.01,
  )
  return option?.value ?? '1'
}

function rateMultiplier(value: string): number {
  const option = RATE_OPTIONS.find((candidate) => candidate.value === value)
  if (!option) throw new Error(`Unknown rate option ${value}`)
  return option.multiplier
}

function RateSelect({
  automationId,
  multiplier,
  disabled,
  redBorder = false,
  gridRow,
  gridCol,
  onPick,
}: {
  automationId: string
  multiplier: number
  disabled: boolean
  redBorder?: boolean
  gridRow: number
  gridCol: string
  onPick: (multiplier: number) => void
}) {
  return (
    <Select
      value={rateValue(multiplier)}
      disabled={disabled}
      onValueChange={(value) => onPick(rateMultiplier(value))}
    >
      <SelectTrigger
        size="sm"
        data-automation-id={automationId}
        data-grid-nav-cell="true"
        data-grid-row={gridRow}
        data-grid-col={gridCol}
        className={redBorder ? 'border-red-500' : undefined}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {RATE_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

// ── Cells ────────────────────────────────────────────────────────────────

type CellProps = CellContext<typeof editableGridFeatures, TimesheetGridRow>

function focusAutomationId(id: string) {
  // Deferred so the target exists after the render that revealed it.
  setTimeout(() => {
    const el = document.querySelector(`[data-automation-id="${id}"]`)
    if (el instanceof HTMLElement) {
      el.focus()
      if (el instanceof HTMLInputElement) el.select()
    }
  }, 0)
}

function JobPickerCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const selected = jobForRow(context, gridRow)
  const isDraft = gridRow.type === 'draft'
  // A saved line's job lives on its cost set — retargeting is delete-and-
  // recreate, so the picker locks. The NEXT phantom also locks while a
  // create is in flight (the keyboard spec asserts the disabled state).
  const disabled =
    !isDraft ||
    context.isPersisting(gridRow.localId) ||
    (context.anyPersisting && context.isPhantom(gridRow.localId))

  if (gridRow.type === 'server' && selected === null) {
    // The job left the active list (e.g. archived): show its stored identity.
    return (
      <button
        type="button"
        disabled
        className="block w-full max-w-[10ch] truncate px-2 py-1 text-left text-sm opacity-50"
        data-automation-id={`SmartTimesheetTable-jobPicker-${row.index}-trigger`}
        data-entry-seq={gridRow.line.entry_seq ?? undefined}
      >
        #{gridRow.line.job_number}
      </button>
    )
  }

  return (
    <TimesheetJobPicker
      automationIdPrefix={`SmartTimesheetTable-jobPicker-${row.index}`}
      jobs={context.jobs}
      selected={selected}
      disabled={disabled}
      entrySeq={gridRow.type === 'server' ? gridRow.line.entry_seq : null}
      gridRow={row.index}
      onSelect={(job) => {
        if (gridRow.type !== 'draft') return
        context.updateDraft(gridRow.localId, applyJobPick(gridRow.draft, job))
        focusAutomationId(`SmartTimesheetTable-hours-${row.index}`)
      }}
    />
  )
}

function CompanyCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const name =
    gridRow.type === 'server'
      ? (gridRow.line.company_name ?? '')
      : (jobForRow(context, gridRow)?.company_name ?? '')
  return (
    <span
      className="block max-w-[24ch] truncate text-sm text-slate-600"
      data-automation-id={`SmartTimesheetTable-company-${row.index}`}
      title={name}
    >
      {name}
    </span>
  )
}

function JobNameCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const job = jobForRow(context, gridRow)
  const name = gridRow.type === 'server' ? gridRow.line.job_name : (job?.name ?? '')
  const urgent = job?.is_urgent ?? false
  return (
    <span className="inline-flex max-w-[55ch] items-center gap-1">
      <span
        className="truncate text-sm text-slate-700"
        data-automation-id={`SmartTimesheetTable-jobName-${row.index}`}
        title={name}
      >
        {name}
      </span>
      {urgent && (
        <span
          className="inline-block rounded-full border border-amber-400 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700"
          data-automation-id={`SmartTimesheetTable-urgentBadge-${row.index}`}
        >
          Urgent
        </span>
      )}
      {gridRow.type === 'draft' && context.isFailed(gridRow.localId) && <SaveFailedBadge />}
    </span>
  )
}

function HoursCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const hours = gridRow.type === 'server' ? Number(gridRow.line.quantity) : gridRow.draft.hours
  // Local buffer while typing; the committed display is the humanised form
  // ('2h', '3h 30m' — asserted as the input's VALUE by the specs).
  const [local, setLocal] = useState('')
  const [dirty, setDirty] = useState(false)
  const display = dirty ? local : hours > 0 ? formatHoursDisplay(hours) : ''
  const disabled = gridRow.type === 'draft' && context.isPersisting(gridRow.localId)

  const commit = () => {
    if (!dirty) return
    setDirty(false)
    const parsed = parseHoursInput(local, hours)
    if (parsed === hours) return
    if (gridRow.type === 'server') {
      // Sending meta alongside quantity routes the write through the server
      // rate pipeline (created_from_timesheet repricing).
      context.patchLine(gridRow.line.id, {
        quantity: String(parsed),
        meta: gridRow.line.meta,
      })
    } else {
      context.updateDraft(gridRow.localId, { hours: parsed })
    }
  }

  return (
    <input
      value={display}
      disabled={disabled}
      inputMode="decimal"
      aria-label={`Hours row ${row.index}`}
      className={`w-20 rounded border border-slate-200 px-2 py-1 text-right text-sm ${hours > 8 ? 'font-bold text-red-600' : ''}`}
      data-automation-id={`SmartTimesheetTable-hours-${row.index}`}
      onChange={(event) => {
        setDirty(true)
        setLocal(event.target.value)
      }}
      onFocus={(event) => event.target.select()}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key !== 'Enter') return
        event.preventDefault()
        event.currentTarget.blur()
        // Enter on a ready draft creates immediately (v1 createOnHoursCommit).
        if (gridRow.type === 'draft') context.commitDraft(gridRow.localId)
      }}
    />
  )
}

function DescriptionCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const serverValue =
    gridRow.type === 'server' ? (gridRow.line.desc ?? '') : gridRow.draft.description
  const field = useAutosaveField(
    serverValue,
    (value) => {
      if (gridRow.type === 'server') {
        // ADR 0040: blank clears to null, never an empty string.
        context.patchLine(gridRow.line.id, { desc: value.trim() === '' ? null : value })
      } else {
        context.updateDraft(gridRow.localId, { description: value })
      }
    },
    undefined,
    gridRow.type === 'server',
  )
  const disabled = gridRow.type === 'draft' && context.isPersisting(gridRow.localId)

  return (
    <textarea
      rows={1}
      value={field.value}
      disabled={disabled}
      aria-label={`Description row ${row.index}`}
      className="w-full min-w-[28ch] resize-y rounded border border-slate-200 px-2 py-1 text-sm"
      data-automation-id={`SmartTimesheetTable-description-${row.index}`}
      onChange={(event) => field.onChange(event.target.value)}
      onFocus={field.onFocus}
      onBlur={field.onBlur}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          // Enter commits (blur flushes the autosave buffer) — the create
          // spec asserts the PATCH fires on Enter, not on a newline.
          event.preventDefault()
          event.currentTarget.blur()
          return
        }
        if (event.key === 'Tab' && !event.shiftKey) {
          // Natural Tab would land on this row's labour select and never
          // exit the row. v1 overrides description's Tab to the next row's
          // picker; for a draft that commit is the POST itself.
          event.preventDefault()
          event.currentTarget.blur()
          if (gridRow.type === 'draft') {
            context.commitDraft(gridRow.localId)
          } else {
            focusAutomationId(`SmartTimesheetTable-jobPicker-${row.index + 1}-trigger`)
          }
        }
      }}
    />
  )
}

function LabourTypeCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const job = jobForRow(context, gridRow)
  const rates = job?.labour_rates ?? []
  const current =
    gridRow.type === 'server' ? gridRow.line.labour_subtype : gridRow.draft.labour_subtype
  const disabled =
    rates.length === 0 || (gridRow.type === 'draft' && context.isPersisting(gridRow.localId))
  // A saved row whose job left the active list keeps showing its stored
  // subtype (the fallback label) rather than a blank control.
  const fallbackLabel =
    gridRow.type === 'server' && current !== null ? (subtypeName(rates, current) ?? '') : ''

  return (
    <Select
      value={current ?? undefined}
      disabled={disabled}
      onValueChange={(value) => {
        if (gridRow.type === 'server') {
          // labour_subtype alone: the backend pulls stored meta and reprices.
          context.patchLine(gridRow.line.id, { labour_subtype: value })
        } else {
          context.updateDraft(gridRow.localId, { labour_subtype: value })
        }
      }}
    >
      <SelectTrigger
        size="sm"
        data-automation-id={`SmartTimesheetTable-labourType-${row.index}`}
        data-grid-nav-cell="true"
        data-grid-row={row.index}
        data-grid-col="labourType"
      >
        <SelectValue placeholder={fallbackLabel} />
      </SelectTrigger>
      <SelectContent>
        {rates.map((rate) => (
          <SelectItem key={rate.labour_subtype} value={rate.labour_subtype}>
            {rate.labour_subtype_name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function RateCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const multiplier =
    gridRow.type === 'server'
      ? lineWageMultiplier(gridRow.line)
      : gridRow.draft.wage_rate_multiplier
  const disabled = gridRow.type === 'draft' && context.isPersisting(gridRow.localId)

  return (
    <RateSelect
      automationId={`SmartTimesheetTable-rate-${row.index}`}
      multiplier={multiplier}
      disabled={disabled}
      gridRow={row.index}
      gridCol="rate"
      onPick={(picked) => {
        // The wage select changes ONLY the wage multiplier. v1's setRate
        // nominally mirrored into bill, but its override check counted a
        // present bill_rate_multiplier key as explicit — and setJob always
        // writes that key — so the mirror was unreachable once a job was
        // picked and never ran on saved rows. Mirroring here would clobber
        // the urgent 1.5x default or flip a shop job billable (a 422);
        // applyJobPick alone owns the bill defaults.
        if (gridRow.type === 'server') {
          context.patchLine(gridRow.line.id, {
            meta: { ...lineMeta(gridRow.line), wage_rate_multiplier: picked },
          })
        } else {
          context.updateDraft(gridRow.localId, { wage_rate_multiplier: picked })
        }
      }}
    />
  )
}

function PayItemCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  // Test hook only (hidden): the pay-item specs read this text on SAVED rows,
  // where the server-picked pay item id resolves through the pay-items list.
  const name =
    gridRow.type === 'server'
      ? (context.payItems.find((item) => item.id === gridRow.line.xero_pay_item)?.name ?? '')
      : ''
  return (
    <span className="hidden" data-automation-id={`SmartTimesheetTable-payItem-${row.index}`}>
      {name}
    </span>
  )
}

function BillRateCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const job = jobForRow(context, gridRow)
  const billMultiplier =
    gridRow.type === 'server'
      ? lineBillMultiplier(gridRow.line)
      : gridRow.draft.bill_rate_multiplier
  const wageMultiplier =
    gridRow.type === 'server'
      ? lineWageMultiplier(gridRow.line)
      : gridRow.draft.wage_rate_multiplier
  const billable =
    gridRow.type === 'server' ? lineIsBillable(gridRow.line) : gridRow.draft.is_billable
  const disabled = gridRow.type === 'draft' && context.isPersisting(gridRow.localId)
  // A billable non-shop row whose customer charge diverges from the wage
  // multiplier gets flagged (v1's red border).
  const redBorder = billable && !(job?.shop_job ?? false) && billMultiplier !== wageMultiplier

  return (
    <RateSelect
      automationId={`SmartTimesheetTable-billRate-${row.index}`}
      multiplier={billMultiplier}
      disabled={disabled}
      redBorder={redBorder}
      gridRow={row.index}
      gridCol="billRate"
      onPick={(picked) => {
        if (gridRow.type === 'server') {
          context.patchLine(gridRow.line.id, {
            meta: {
              ...lineMeta(gridRow.line),
              bill_rate_multiplier: picked,
              is_billable: picked > 0,
            },
          })
        } else {
          context.updateDraft(gridRow.localId, {
            bill_rate_multiplier: picked,
            is_billable: picked > 0,
            billExplicit: true,
          })
        }
      }}
    />
  )
}

function WageCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  const amount =
    gridRow.type === 'server'
      ? gridRow.line.total_cost
      : gridRow.draft.hours * context.staffWageRate * gridRow.draft.wage_rate_multiplier
  return (
    <span
      className="block text-right text-sm font-medium text-emerald-700"
      data-automation-id={`SmartTimesheetTable-wage-${row.index}`}
    >
      {formatCurrency(amount)}
    </span>
  )
}

function BillCell({ row }: CellProps) {
  const gridRow = row.original
  let amount: number
  if (gridRow.type === 'server') {
    amount = gridRow.line.total_rev
  } else if (gridRow.draft.job === null || gridRow.draft.hours <= 0) {
    amount = 0
  } else {
    amount =
      gridRow.draft.hours *
      rateForSubtype(gridRow.draft.job.labour_rates, gridRow.draft.labour_subtype) *
      gridRow.draft.bill_rate_multiplier
  }
  return (
    <span
      className="block text-right text-sm font-medium text-blue-700"
      data-automation-id={`SmartTimesheetTable-bill-${row.index}`}
    >
      {formatCurrency(amount)}
    </span>
  )
}

function ActionsCell({ row, table }: CellProps) {
  const context = cellMeta(table)
  const gridRow = row.original
  if (gridRow.type === 'draft') {
    if (context.isPhantom(gridRow.localId)) return null
    return (
      <button
        type="button"
        aria-label={`Discard draft row ${row.index}`}
        // Locked in flight like the inputs: discarding a persisting draft
        // would drop the row while its POST still lands.
        disabled={context.isPersisting(gridRow.localId)}
        className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
        data-automation-id={`SmartTimesheetTable-actions-${row.index}-delete`}
        // Pointer-down beats the blur-triggered row-exit commit.
        onPointerDown={(event) => {
          event.preventDefault()
          if (context.isPersisting(gridRow.localId)) return
          context.removeDraft(gridRow.localId)
        }}
      >
        <Trash2 className="h-4 w-4" />
      </button>
    )
  }
  return (
    <span className="inline-flex items-center gap-1">
      {!gridRow.line.approved && (
        <button
          type="button"
          aria-label={`Approve row ${row.index}`}
          className="rounded p-1 text-emerald-600 hover:bg-emerald-50"
          data-automation-id={`SmartTimesheetTable-actions-${row.index}-approve`}
          onClick={() => context.approveLine(gridRow.line.id)}
        >
          <Check className="h-4 w-4" />
        </button>
      )}
      <button
        type="button"
        aria-label={`Delete row ${row.index}`}
        className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
        data-automation-id={`SmartTimesheetTable-actions-${row.index}-delete`}
        onClick={() => context.deleteLine(gridRow.line.id)}
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </span>
  )
}

// Module-level constant so cell components keep identity across renders —
// rebuilding them would remount (and blur) every input on each grid render.
const COLUMNS: ColumnDef<typeof editableGridFeatures, TimesheetGridRow>[] = [
  { id: 'jobNumber', header: 'Job', cell: JobPickerCell },
  { id: 'company', header: 'Company', cell: CompanyCell },
  { id: 'jobName', header: 'Job Name', cell: JobNameCell },
  { id: 'hours', header: 'Hours', cell: HoursCell },
  { id: 'description', header: 'Description', cell: DescriptionCell },
  { id: 'labourType', header: 'Labour type', cell: LabourTypeCell },
  { id: 'rate', header: 'Wage', cell: RateCell },
  { id: 'payItem', header: '', cell: PayItemCell },
  { id: 'billRate', header: 'Invoice', cell: BillRateCell },
  { id: 'wage', header: 'Wage $', cell: WageCell },
  { id: 'bill', header: 'Invoice $', cell: BillCell },
  { id: 'actions', header: '', cell: ActionsCell },
]

const EDITABLE_COLUMNS = new Set(['hours', 'description', 'labourType', 'rate', 'billRate'])

/**
 * The timesheet entry grid — CostLineGrid's sibling over the shared draft
 * machinery. The selector contract is load-bearing for the E2E suite:
 * `.smart-timesheet-table` on the root, `DataTable-row-N` + `data-row-id` per
 * row with exactly one trailing phantom, and the SmartTimesheetTable-*-N
 * cell families (the picker derives -trigger/-search/-list/-option-N).
 */
export function SmartTimesheetTable({
  entries,
  jobs,
  payItems,
  staffId,
  date,
  staffWageRate,
  patchLine,
  createLine,
  deleteLine,
  approveLine,
}: SmartTimesheetTableProps) {
  // Bumped when a create lands; the effect below hands focus to the fresh
  // phantom's picker (trigger focus → auto-open → search autofocus).
  const [focusPhantomToken, setFocusPhantomToken] = useState(0)

  const draftRows = useDraftRows<TimesheetDraft>({
    emptyDraft: emptyTimesheetDraft,
    draftIsEmpty,
    isReady: draftIsReady,
    persist: (draft, callbacks) => {
      if (draft.job === null) throw new Error('a ready timesheet draft always has a job')
      createLine(
        draft.job,
        {
          desc: draft.description.trim() === '' ? null : draft.description,
          quantity: String(draft.hours),
          accounting_date: date,
          meta: {
            staff_id: staffId,
            date,
            is_billable: draft.is_billable,
            wage_rate_multiplier: draft.wage_rate_multiplier,
            bill_rate_multiplier: draft.bill_rate_multiplier,
            created_from_timesheet: true,
          },
          labour_subtype: draft.labour_subtype ?? undefined,
        },
        { onCreated: () => callbacks.onCreated(), onFailed: callbacks.onFailed },
      )
    },
    onCreated: () => setFocusPhantomToken((token) => token + 1),
  })

  useEffect(() => {
    if (focusPhantomToken === 0) return
    // The fresh phantom is the LAST picker trigger in the grid.
    const triggers = document.querySelectorAll(
      '[data-automation-id^="SmartTimesheetTable-jobPicker-"][data-automation-id$="-trigger"]',
    )
    const last = triggers[triggers.length - 1]
    if (last instanceof HTMLElement) last.focus()
  }, [focusPhantomToken])

  const rows = useMemo<TimesheetGridRow[]>(
    () => [
      ...entries.map((line): TimesheetGridRow => ({ type: 'server', line })),
      ...draftRows.drafts.map((entry): TimesheetGridRow => ({ type: 'draft', ...entry })),
    ],
    [entries, draftRows.drafts],
  )

  const meta: TimesheetCellContext = {
    jobs,
    payItems,
    staffWageRate,
    patchLine,
    deleteLine,
    approveLine,
    updateDraft: draftRows.updateDraft,
    commitDraft: draftRows.commitDraft,
    removeDraft: draftRows.removeDraft,
    isPhantom: draftRows.isPhantom,
    isPersisting: draftRows.isPersisting,
    anyPersisting: draftRows.anyPersisting,
    isFailed: draftRows.isFailed,
  }

  const table = useTable({
    features: editableGridFeatures,
    data: rows,
    columns: COLUMNS,
    getRowId: (row) => (row.type === 'server' ? row.line.id : row.localId),
    meta: { timesheetGrid: meta },
  })

  return (
    <DataTable
      table={table}
      editableColumns={EDITABLE_COLUMNS}
      draftLocalId={(row) => (row.type === 'draft' ? row.localId : null)}
      rowExitHandlers={draftRows.rowExitHandlers}
      wrapperClassName="smart-timesheet-table"
    />
  )
}
