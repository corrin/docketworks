<script setup lang="ts">
/**
 * SmartTimesheetTable.vue
 *
 * Inline editor for a staff member's daily timesheet entries. Mirrors the
 * pattern used by SmartCostLinesTable.vue (DataTable + shadcn cells, v-model
 * directly on the live row reference, autosave on blur).
 *
 * The previous AG-grid implementation used a snapshot-then-apply autosave
 * pattern that raced with the Enter key handler and silently wiped user
 * input. That class of bug is structurally impossible here: cells are
 * always-mounted, write directly to the row via v-model / Object.assign, and
 * autosave reads the live row at fire time.
 *
 * Backend types: TimesheetCostLine fields are snake_case throughout — no
 * dual naming (no jobNumber/job_number, hours/quantity, wage/total_cost
 * pairs). When the parent needs camelCase, it does the mapping.
 */

import { computed, h, nextTick, onUnmounted, ref, useId, watch } from 'vue'
import DataTable from '../DataTable.vue'
import { Textarea } from '../ui/textarea'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../ui/select'
import TimesheetActionsCell from './TimesheetActionsCell.vue'
import TimesheetJobPicker from './TimesheetJobPicker.vue'
import HoursCell from './HoursCell.vue'

import { useCostLineAutosave } from '@/composables/useCostLineAutosave'
import {
  type GridCellKeydownOptions,
  gridCellAttrs,
  handleGridCellKeydown,
  useGridKeyboardNav,
} from '@/composables/useGridKeyboardNav'
import { usePhantomRow } from '@/composables/usePhantomRow'
import { costlineService } from '@/services/costline.service'
import { formatCurrency } from '@/utils/string-formatting'
import { logError } from '@/utils/error-handler'
import { debugLog } from '@/utils/debug'
import {
  getRateMultiplier,
  getRateTypeFromMultiplier,
  getMeta,
  getMultiplier,
  getBillMultiplier,
  calculatedWage,
  calculatedBill,
  parseHoursInput,
} from '@/utils/timesheetCalc'
import { rateForSubtype } from '@/utils/labourRates'

import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type TimesheetCostLine = z.infer<typeof schemas.TimesheetCostLine>
type Job = z.infer<typeof schemas.ModernTimesheetJob>
type CostLine = z.infer<typeof schemas.CostLine>
type PatchedCostLineCreateUpdate = z.infer<typeof schemas.PatchedCostLineCreateUpdateRequest>

interface PayItem {
  id: string
  name: string
  multiplier: number
}

const props = withDefaults(
  defineProps<{
    entries: TimesheetCostLine[]
    staffId: string
    staffWageRate: number
    accountingDate: string
    jobs: Job[]
    /** Map of multiplier (as string, e.g. "1.5") → pay item, used when rate changes. */
    payItemsByMultiplier?: Record<string, PayItem | undefined>
    readOnly?: boolean
    createPending?: boolean
    focusPhantomToken?: number
  }>(),
  {
    readOnly: false,
    createPending: false,
    focusPhantomToken: 0,
    payItemsByMultiplier: () => ({}),
  },
)

const emit = defineEmits<{
  'create-entry': [entry: TimesheetCostLine]
  'delete-entry': [id: string]
  'approve-entry': [id: string]
}>()

function setMeta(entry: TimesheetCostLine, patch: Record<string, unknown>): void {
  const merged = { ...getMeta(entry), ...patch }
  Object.assign(entry, { meta: merged })
}

// ────────────────────────────────────────────────────────────────────────────
// Phantom empty entry (always-present trailing row)
// ────────────────────────────────────────────────────────────────────────────

function makeEmptyEntry(): TimesheetCostLine {
  const now = new Date().toISOString()
  // Rates are per-job (per labour subtype); the real charge-out rate is set
  // when a job is picked (setJob), so the phantom row starts at 0.
  return {
    id: '',
    kind: 'time',
    desc: '',
    quantity: 0,
    unit_cost: props.staffWageRate,
    unit_rev: 0,
    ext_refs: {},
    meta: {
      staff_id: props.staffId,
      date: props.accountingDate,
      is_billable: true,
      wage_rate_multiplier: 1.0,
    },
    created_at: now,
    updated_at: now,
    accounting_date: props.accountingDate,
    xero_time_id: null,
    xero_expense_id: null,
    xero_last_modified: null,
    xero_last_synced: null,
    approved: false,
    xero_pay_item: null,
    total_cost: 0,
    total_rev: 0,
    job_id: '',
    job_number: 0,
    job_name: '',
    client_name: '',
    charge_out_rate: 0,
    wage_rate: props.staffWageRate,
    xero_pay_item_name: '',
    labour_subtype: null,
    labour_subtype_name: '',
  } as TimesheetCostLine
}

const pendingCreateEntry = ref<TimesheetCostLine | null>(null)
const {
  phantomRow: emptyEntry,
  displayRows: displayEntries,
  resetPhantom,
  selectPhantom,
} = usePhantomRow<TimesheetCostLine>({
  rows: () => props.entries,
  extraRows: () => (pendingCreateEntry.value ? [pendingCreateEntry.value] : []),
  makePhantom: makeEmptyEntry,
})
const createdOnce = new Set<TimesheetCostLine>()
const billOverrides = new WeakSet<TimesheetCostLine>()

function hasExplicitBillOverride(entry: TimesheetCostLine): boolean {
  return (
    billOverrides.has(entry) ||
    Object.prototype.hasOwnProperty.call(getMeta(entry), 'bill_rate_multiplier')
  )
}

function isEntryReady(entry: TimesheetCostLine): boolean {
  const hasJob = Boolean(entry.job_id) || (entry.job_number != null && entry.job_number > 0)
  const hours = entry.quantity ?? 0
  return hasJob && hours > 0
}

function maybeEmitCreate(entry: TimesheetCostLine): void {
  if (props.createPending) return
  if (createdOnce.has(entry)) return
  if (!isEntryReady(entry)) return
  createdOnce.add(entry)
  if (entry === emptyEntry.value) {
    pendingCreateEntry.value = entry
  }
  emit('create-entry', entry)
  if (entry === emptyEntry.value) resetPhantom()
}

// ────────────────────────────────────────────────────────────────────────────
// Autosave for existing rows
// ────────────────────────────────────────────────────────────────────────────

const autosave = useCostLineAutosave({
  debounceMs: 600,
  statusSource: 'timesheet-cost-lines',
  saveFn: async (id: string, patch: PatchedCostLineCreateUpdate) => {
    try {
      return await costlineService.updateCostLine(id, patch)
    } catch (err) {
      const responseBody =
        err && typeof err === 'object' && 'response' in err
          ? ((err as { response?: { data?: unknown; status?: number } }).response ?? null)
          : null
      logError('SmartTimesheetTable.updateCostLine', err, {
        costLineId: id,
        patch,
        responseStatus: responseBody?.status,
        responseBody: responseBody?.data,
      })
      throw err
    }
  },
  onOptimisticApply: (line, patch) => {
    Object.assign(line, patch as Partial<CostLine>)
  },
  onRollback: (line, snap) => {
    Object.assign(line, snap)
    // The actual error message is shown by useCostLineAutosave's own toast.
    // We log details via the saveFn wrapper above; keep this rollback notice
    // simple so users aren't toast-spammed.
    debugLog('SmartTimesheetTable: row rolled back after save failure', { lineId: line.id })
  },
  onSaved: (line, response, patch) => {
    // The backend reprices unit_rev when labour_subtype changes; refresh the
    // row from the canonical response.
    if (!('labour_subtype' in patch)) return
    Object.assign(line, {
      labour_subtype: response.labour_subtype ?? null,
      ...(response.unit_rev !== undefined && { unit_rev: response.unit_rev }),
      ...(response.total_rev !== undefined && { total_rev: response.total_rev }),
    })
  },
})

onUnmounted(() => {
  autosave.clearStatus()
})

function buildPatch(
  entry: TimesheetCostLine,
  fields: (keyof PatchedCostLineCreateUpdate)[],
): PatchedCostLineCreateUpdate {
  const patch: Record<string, unknown> = {}
  const src = entry as unknown as Record<string, unknown>
  for (const f of fields) {
    patch[f] = src[f]
  }
  return patch as PatchedCostLineCreateUpdate
}

function commit(entry: TimesheetCostLine, fields: (keyof PatchedCostLineCreateUpdate)[]): void {
  if (!entry.id) {
    maybeEmitCreate(entry)
    return
  }
  const patch = buildPatch(entry, fields)
  autosave.scheduleSave(entry as unknown as CostLine, patch, patch as Partial<CostLine>)
}

// ────────────────────────────────────────────────────────────────────────────
// Mutations
// ────────────────────────────────────────────────────────────────────────────

function isCreateLocked(entry: TimesheetCostLine): boolean {
  return props.createPending && !entry.id
}

function shouldDeferCreateForDescription(
  entry: TimesheetCostLine,
  event?: FocusEvent,
  reason?: 'forward-tab' | null,
): boolean {
  if (entry.id) return false
  if (!isEntryReady(entry)) return false
  if (reason === 'forward-tab') return true
  const relatedTarget = event?.relatedTarget
  if (!(relatedTarget instanceof HTMLElement)) return false
  const idx = displayEntries.value.indexOf(entry)
  return (
    relatedTarget.dataset.gridRow === String(idx) && relatedTarget.dataset.gridCol === 'description'
  )
}

function setHours(
  entry: TimesheetCostLine,
  raw: string,
  event?: FocusEvent,
  reason?: 'forward-tab' | null,
): void {
  if (isCreateLocked(entry)) return
  const fallback = entry.quantity ?? 0
  const v = parseHoursInput(raw, fallback)
  if (v === fallback) return
  Object.assign(entry, { quantity: v })
  Object.assign(entry, {
    total_cost: calculatedWage(entry),
    total_rev: calculatedBill(entry),
  })
  if (shouldDeferCreateForDescription(entry, event, reason)) {
    createOnHoursCommit.delete(entry)
    return
  }
  if (entry.id || createOnHoursCommit.has(entry) || String(entry.desc ?? '').trim()) {
    createOnHoursCommit.delete(entry)
    commit(entry, ['quantity', 'unit_cost', 'unit_rev', 'meta'])
  }
}

function setDescription(entry: TimesheetCostLine, val: string): void {
  if (isCreateLocked(entry)) return
  // No equality check: the description's onUpdate:modelValue handler already
  // pre-mutates entry.desc on each keystroke (unlike Hours/Rate which keep a
  // local string until blur), so by the time onBlur calls us entry.desc and
  // val are always equal. An equality check here is dead code that prevents
  // commit from ever running. The autosave layer dedups identical patches.
  Object.assign(entry, { desc: val })
  commit(entry, ['desc'])
}

function setBill(entry: TimesheetCostLine, rateType: string): void {
  if (isCreateLocked(entry)) return
  const mult = getRateMultiplier(rateType)
  if (getBillMultiplier(entry) === mult && hasExplicitBillOverride(entry)) return
  billOverrides.add(entry)
  setMeta(entry, { bill_rate_multiplier: mult, is_billable: mult > 0 })
  Object.assign(entry, {
    unit_rev: Math.round((entry.charge_out_rate ?? 0) * mult * 100) / 100,
    total_rev: calculatedBill(entry),
  })
  commit(entry, ['unit_rev', 'meta'])
}

function setRate(entry: TimesheetCostLine, rateType: string): void {
  if (isCreateLocked(entry)) return
  const mult = getRateMultiplier(rateType)
  if (getMultiplier(entry) === mult) return
  // The backend rejects extra meta keys; rate_type is derived from
  // wage_rate_multiplier (see getRateTypeFromMultiplier) and not stored.
  const shouldMirrorBill = !hasExplicitBillOverride(entry)
  setMeta(entry, {
    wage_rate_multiplier: mult,
    ...(shouldMirrorBill && { bill_rate_multiplier: mult, is_billable: mult > 0 }),
  })
  if (mult === 1.0) {
    // Switching back to Ord: restore the job's default pay item rather than
    // leaving the previous multiplier's pay item attached.
    const job = props.jobs.find((j) => j.id === entry.job_id)
    Object.assign(entry, {
      xero_pay_item: job?.default_xero_pay_item_id ?? null,
      xero_pay_item_name: job?.default_xero_pay_item_name ?? '',
    })
  } else {
    // Non-Ord: use the dedicated Xero pay item registered for that multiplier.
    const payItem = props.payItemsByMultiplier?.[String(mult)]
    if (payItem) {
      debugLog('SmartTimesheetTable: resolved Xero pay item for pay rate', {
        multiplier: mult,
        payItemId: payItem.id,
        payItemName: payItem.name,
      })
      Object.assign(entry, {
        xero_pay_item: payItem.id,
        xero_pay_item_name: payItem.name,
      })
    }
  }
  Object.assign(entry, {
    unit_cost: Math.round((entry.wage_rate ?? 0) * mult * 100) / 100,
    ...(shouldMirrorBill && {
      unit_rev: Math.round((entry.charge_out_rate ?? 0) * mult * 100) / 100,
    }),
    total_cost: calculatedWage(entry),
    total_rev: calculatedBill(entry),
  })
  commit(entry, ['unit_cost', 'unit_rev', 'meta', 'xero_pay_item'])
}

function isJobNonBillable(job: Job): boolean {
  // The cost-line validator rejects billable time on shop jobs and on the
  // 'special' status (rejected/internal). ModernTimesheetJob now exposes
  // `shop_job` directly via the timesheet job serializer.
  return !!job.shop_job || job.status === 'special'
}

function entryJob(entry: TimesheetCostLine): Job | undefined {
  return props.jobs.find((j) => j.id === entry.job_id || j.job_number === entry.job_number)
}

function isEntryShopJob(entry: TimesheetCostLine): boolean {
  return !!entryJob(entry)?.shop_job
}

function setLabourType(entry: TimesheetCostLine, subtypeId: string): void {
  if (isCreateLocked(entry)) return
  if (entry.labour_subtype === subtypeId) return
  const job = entryJob(entry)
  const rateEntry = job?.labour_rates.find((r) => r.labour_subtype === subtypeId)
  Object.assign(entry, {
    labour_subtype: subtypeId,
    labour_subtype_name: rateEntry?.labour_subtype_name ?? entry.labour_subtype_name,
    ...(rateEntry && { charge_out_rate: rateEntry.charge_out_rate ?? 0 }),
  })
  const mult = getBillMultiplier(entry)
  Object.assign(entry, {
    unit_rev: Math.round((entry.charge_out_rate ?? 0) * mult * 100) / 100,
    total_rev: calculatedBill(entry),
  })
  // Saved rows: PATCH labour_subtype only — the backend reprices unit_rev and
  // the autosave onSaved hook refreshes the row from the response. New rows
  // carry the selection into the create payload.
  commit(entry, ['labour_subtype'])
}

function setJob(entry: TimesheetCostLine, job: Job): void {
  if (isCreateLocked(entry)) return
  // Rate for the entry's labour subtype; new rows have no subtype yet (the
  // backend defaults it from the worker), so display the workshop rate.
  const rate = rateForSubtype(job.labour_rates, entry.labour_subtype)
  Object.assign(entry, {
    job_id: job.id,
    job_number: job.job_number,
    job_name: job.name ?? '',
    client_name: job.client_name ?? '',
    charge_out_rate: rate,
  })
  // Adopt the job's default pay item if the user hasn't picked a non-Ord rate.
  if (getMultiplier(entry) === 1.0 && job.default_xero_pay_item_id) {
    Object.assign(entry, {
      xero_pay_item: job.default_xero_pay_item_id,
      xero_pay_item_name: job.default_xero_pay_item_name ?? '',
    })
  }
  // Shop jobs and 'special' status jobs are non-billable; force the meta flag
  // so the user (and the backend) see a consistent state.
  if (isJobNonBillable(job)) {
    setMeta(entry, { is_billable: false, bill_rate_multiplier: 0.0 })
  }
  // unit_rev is the bill rate: subtype rate x bill multiplier (zero after the
  // non-billable forcing above), mirroring setLabourType.
  Object.assign(entry, {
    unit_rev: Math.round(rate * getBillMultiplier(entry) * 100) / 100,
    total_rev: calculatedBill(entry),
  })
  commit(entry, ['unit_rev', 'meta', 'xero_pay_item'])

  // After picking a job, focus the Hours cell on the same row so the user can
  // type without an extra click. The cell renders <HoursCell> inside <Input>.
  void nextTick(() => {
    const idx = displayEntries.value.indexOf(entry)
    if (idx < 0) return
    const cell = containerRef.value?.querySelector(
      `[data-automation-id="SmartTimesheetTable-hours-${idx}"]`,
    )
    if (cell instanceof HTMLInputElement) {
      cell.focus()
      cell.select()
    }
  })
}

// ────────────────────────────────────────────────────────────────────────────
// Keyboard navigation
// ────────────────────────────────────────────────────────────────────────────

const containerRef = ref<HTMLElement | null>(null)
const selectedRowIndex = ref<number>(-1)
const createOnHoursCommit = new WeakSet<TimesheetCostLine>()

const { onKeydown } = useGridKeyboardNav({
  getRowCount: () => displayEntries.value.length,
  getSelectedIndex: () => selectedRowIndex.value,
  setSelectedIndex: (i) => (selectedRowIndex.value = i),
  addLine: () => {
    // Phantom row is always present. Ctrl/Cmd+Enter selects it.
    selectPhantom((index) => (selectedRowIndex.value = index))
  },
  deleteSelected: () => {
    const i = selectedRowIndex.value
    if (i < 0 || i >= displayEntries.value.length) return
    const entry = displayEntries.value[i]
    if (entry.id) emit('delete-entry', String(entry.id))
  },
})

function handleRowClick(entry: TimesheetCostLine): void {
  const idx = displayEntries.value.indexOf(entry)
  if (idx >= 0) selectedRowIndex.value = idx
}

const tableId = useId()

function focusPhantomJobPicker(): void {
  void nextTick(() => {
    const idx = displayEntries.value.indexOf(emptyEntry.value)
    if (idx < 0) return
    const el = containerRef.value?.querySelector(
      `[data-automation-id="SmartTimesheetTable-jobPicker-${idx}-trigger"]`,
    )
    if (el instanceof HTMLElement) el.focus()
  })
}

watch(
  () => props.createPending,
  (pending) => {
    if (pending || !pendingCreateEntry.value) return
    const entry = pendingCreateEntry.value
    const token = props.focusPhantomToken
    void nextTick(() => {
      if (pendingCreateEntry.value === entry && props.focusPhantomToken === token) {
        createdOnce.delete(entry)
      }
    })
  },
)

watch(
  () => props.focusPhantomToken,
  () => {
    pendingCreateEntry.value = null
    focusPhantomJobPicker()
  },
)

function handleCellNav(
  e: KeyboardEvent,
  rowIndex: number,
  columnId: string,
  options?: Partial<GridCellKeydownOptions>,
): boolean {
  return handleGridCellKeydown(e, {
    container: containerRef.value,
    rowIndex,
    columnId,
    ...options,
  })
}

// ────────────────────────────────────────────────────────────────────────────
// Column defs
// ────────────────────────────────────────────────────────────────────────────

type RowCtx = { row: { index: number } }

const columns = computed(() => [
  {
    id: 'jobNumber',
    header: () => h('div', { class: 'text-left' }, 'Job'),
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      // Saved rows: cost-line→job linkage isn't a writable field on the cost
      // line PATCH endpoint (job ownership lives on the parent CostSet). Allow
      // the picker only on the phantom row; a user retargeting an existing
      // entry must delete + recreate.
      return h(TimesheetJobPicker, {
        modelValue: entry.job_number || null,
        jobs: props.jobs,
        disabled: props.readOnly || !!entry.id || isCreateLocked(entry),
        automationIdPrefix: `SmartTimesheetTable-jobPicker-${row.index}`,
        gridRowIndex: row.index,
        gridCol: 'jobNumber',
        entrySeq: entry.entry_seq ?? null,
        onGridKeydown: (e: KeyboardEvent) => handleCellNav(e, row.index, 'jobNumber'),
        onSelect: (job: Job) => setJob(entry, job),
      })
    },
  },
  {
    id: 'client',
    header: 'Client',
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      return h(
        'span',
        {
          class: 'text-sm text-slate-500',
          'data-automation-id': `SmartTimesheetTable-client-${row.index}`,
        },
        entry.client_name || '',
      )
    },
  },
  {
    id: 'jobName',
    header: 'Job Name',
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      const full = entry.job_name || ''
      // Fixed visual width with CSS-driven ellipsis. Full name on hover.
      return h(
        'span',
        {
          class: 'block max-w-[55ch] truncate text-sm text-slate-700 font-medium',
          'data-automation-id': `SmartTimesheetTable-jobName-${row.index}`,
          title: full,
        },
        full,
      )
    },
  },
  {
    id: 'hours',
    header: () => h('div', { class: 'text-right' }, 'Hours'),
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      return h(HoursCell, {
        hours: entry.quantity ?? 0,
        disabled: props.readOnly || isCreateLocked(entry),
        automationId: `SmartTimesheetTable-hours-${row.index}`,
        ...gridCellAttrs(row.index, 'hours'),
        onCommit: (raw: string, event: FocusEvent, reason: 'forward-tab' | null) =>
          setHours(entry, raw, event, reason),
        onKeydown: (e: KeyboardEvent) => {
          if (e.key === 'Enter') createOnHoursCommit.add(entry)
          return handleCellNav(e, row.index, 'hours')
        },
      })
    },
  },
  {
    id: 'description',
    header: () => h('div', { class: 'text-left min-w-[28ch]' }, 'Description'),
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      return h(Textarea, {
        modelValue: entry.desc ?? '',
        disabled: props.readOnly || isCreateLocked(entry),
        rows: 1,
        autocomplete: 'off',
        class: 'w-full min-w-[28ch] min-h-[2.25rem] text-sm',
        'data-automation-id': `SmartTimesheetTable-description-${row.index}`,
        ...gridCellAttrs(row.index, 'description'),
        onKeydown: (e: KeyboardEvent) => {
          const nextRow = Math.min(row.index + 1, displayEntries.value.length - 1)
          if (
            handleCellNav(e, row.index, 'description', {
              container: containerRef.value,
              rowIndex: row.index,
              columnId: 'description',
              tabTarget: { kind: 'column', rowIndex: nextRow, columnId: 'jobNumber' },
              enterTarget: { kind: 'column', rowIndex: nextRow, columnId: 'jobNumber' },
            })
          )
            return
          e.stopPropagation()
        },
        'onUpdate:modelValue': (v: string | number) => {
          Object.assign(entry, { desc: typeof v === 'string' ? v : String(v) })
        },
        onBlur: () => setDescription(entry, entry.desc ?? ''),
      })
    },
  },
  {
    id: 'labourType',
    header: 'Labour type',
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      const job = entryJob(entry)
      // Options come from the job's per-subtype rates. Saved rows whose job is
      // no longer in the active list still show their stored subtype name.
      const options = job
        ? job.labour_rates.map((r) => ({ id: r.labour_subtype, name: r.labour_subtype_name }))
        : entry.labour_subtype
          ? [{ id: entry.labour_subtype, name: entry.labour_subtype_name || 'Labour' }]
          : []
      return h(
        Select,
        {
          modelValue: entry.labour_subtype ?? '',
          disabled: props.readOnly || isCreateLocked(entry) || options.length === 0,
          'onUpdate:modelValue': (v: unknown) => {
            if (typeof v === 'string' && v) setLabourType(entry, v)
          },
        },
        {
          default: () => [
            h(
              SelectTrigger,
              {
                class: 'h-8 text-sm min-w-[12ch]',
                'data-automation-id': `SmartTimesheetTable-labourType-${row.index}`,
                ...gridCellAttrs(row.index, 'labourType'),
              },
              () => [h(SelectValue, { placeholder: 'Default' })],
            ),
            h(SelectContent, {}, () =>
              options.map((opt) => h(SelectItem, { value: opt.id, key: opt.id }, () => opt.name)),
            ),
          ],
        },
      )
    },
  },
  {
    id: 'rate',
    header: 'Wage',
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      const rateType = getRateTypeFromMultiplier(getMultiplier(entry))
      return h(
        Select,
        {
          modelValue: rateType,
          disabled: props.readOnly || isCreateLocked(entry),
          'onUpdate:modelValue': (v: unknown) => {
            if (typeof v === 'string') setRate(entry, v)
          },
        },
        {
          default: () => [
            h(
              SelectTrigger,
              {
                class: 'h-8 text-sm',
                'data-automation-id': `SmartTimesheetTable-rate-${row.index}`,
                ...gridCellAttrs(row.index, 'rate'),
              },
              () => [h(SelectValue)],
            ),
            h(SelectContent, {}, () => [
              h(SelectItem, { value: 'Ord' }, () => 'Ord'),
              h(SelectItem, { value: '1.5' }, () => '1.5x'),
              h(SelectItem, { value: '2.0' }, () => '2.0x'),
              h(SelectItem, { value: 'Unpaid' }, () => 'Unpaid'),
            ]),
          ],
        },
      )
    },
  },
  {
    id: 'payItem',
    header: '',
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      return h(
        'span',
        {
          class: 'hidden',
          'data-automation-id': `SmartTimesheetTable-payItem-${row.index}`,
        },
        entry.xero_pay_item_name || '',
      )
    },
  },
  {
    id: 'billRate',
    header: 'Invoice',
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      const billRateType = getRateTypeFromMultiplier(getBillMultiplier(entry))
      const invoiceDiffersFromWage =
        getBillMultiplier(entry) !== getMultiplier(entry) && !isEntryShopJob(entry)
      return h(
        Select,
        {
          modelValue: billRateType,
          disabled: props.readOnly || isCreateLocked(entry),
          'onUpdate:modelValue': (v: unknown) => {
            if (typeof v === 'string') setBill(entry, v)
          },
        },
        {
          default: () => [
            h(
              SelectTrigger,
              {
                class: [
                  'h-8 text-sm',
                  invoiceDiffersFromWage &&
                    'border-red-500 text-red-700 focus:ring-red-500 [&>span]:text-red-700',
                ],
                'data-automation-id': `SmartTimesheetTable-billRate-${row.index}`,
                ...gridCellAttrs(row.index, 'billRate'),
              },
              () => [h(SelectValue)],
            ),
            h(SelectContent, {}, () => [
              h(SelectItem, { value: 'Ord' }, () => 'Ord'),
              h(SelectItem, { value: '1.5' }, () => '1.5x'),
              h(SelectItem, { value: '2.0' }, () => '2.0x'),
              h(SelectItem, { value: 'Unpaid' }, () => 'Unpaid'),
            ]),
          ],
        },
      )
    },
  },
  {
    id: 'wage',
    header: () => h('div', { class: 'text-right' }, 'Wage $'),
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      return h(
        'span',
        {
          class: 'text-sm font-semibold text-emerald-700 numeric-text block text-right',
          'data-automation-id': `SmartTimesheetTable-wage-${row.index}`,
        },
        formatCurrency(calculatedWage(entry)),
      )
    },
  },
  {
    id: 'bill',
    header: () => h('div', { class: 'text-right' }, 'Invoice $'),
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      return h(
        'span',
        {
          class: 'text-sm font-semibold text-blue-700 numeric-text block text-right',
          'data-automation-id': `SmartTimesheetTable-bill-${row.index}`,
        },
        formatCurrency(calculatedBill(entry)),
      )
    },
  },
  {
    id: 'actions',
    header: '',
    cell: ({ row }: RowCtx) => {
      const entry = displayEntries.value[row.index]
      if (!entry.id) return h('span')
      return h(TimesheetActionsCell, {
        approved: entry.approved !== false,
        canApprove: !!entry.id,
        automationIdPrefix: `SmartTimesheetTable-actions-${row.index}`,
        onApprove: () => emit('approve-entry', String(entry.id)),
        onDelete: () => emit('delete-entry', String(entry.id)),
      })
    },
  },
])
</script>

<template>
  <div
    ref="containerRef"
    tabindex="0"
    class="smart-timesheet-table outline-none focus:outline-none"
    :data-table-id="tableId"
    @keydown="onKeydown"
  >
    <DataTable :columns="columns" :data="displayEntries" hide-footer @row-click="handleRowClick" />
  </div>
</template>

<style scoped>
.smart-timesheet-table :deep(.numeric-input),
.smart-timesheet-table :deep(.numeric-text) {
  font-variant-numeric: tabular-nums;
  font-feature-settings:
    'tnum' 1,
    'lnum' 1;
}

.smart-timesheet-table :deep(input:focus),
.smart-timesheet-table :deep(textarea:focus),
.smart-timesheet-table :deep(button:focus-visible) {
  outline: none;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.6);
}
</style>
