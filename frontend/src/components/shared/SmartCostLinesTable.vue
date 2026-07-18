<script setup lang="ts">
/**
 * SmartCostLinesTable.vue
 *
 * Spreadsheet-like inline editor for Cost Lines with:
 * - Optional Item column (UI-only) that pre-fills description and unit_cost and applies materials markup to unit_rev
 * - Optional Source column (read-only, clickable)
 * - Inline edits with autosave (debounced, optimistic, rollback on failure)
 * - Per-kind editing rules (material, time, adjust)
 * - Keyboard shortcuts via useGridKeyboardNav
 *
 * Non-negotiable rules:
 * - All backend data types must come from generated api.ts
 * - No local backend schemas; UI-only flags (like overridden) are tracked with WeakMaps in composables
 * - Persist changes using existing services/endpoints; do not change API contracts
 */

import { computed, h, onMounted, onUnmounted, ref, nextTick } from 'vue'
import DataTable from '../DataTable.vue'
import { Input } from '../ui/input'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Textarea } from '../ui/textarea'
import ItemSelect from '../../views/purchasing/ItemSelect.vue'
import type { DataTableRowContext } from '../../utils/data-table-types'
import { toast } from 'vue-sonner'
import { debugLog } from '../../utils/debug'
import { formatCurrency } from '../../utils/string-formatting'
import { roundToDecimalPlaces } from '@/utils/number'
import { requiredNumber } from '@/utils/requiredNumber'
import { HelpCircle, Trash2, AlertTriangle, Check } from 'lucide-vue-next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../ui/dialog'

import { useCompanyDefaultsStore } from '../../stores/companyDefaults'
import { useStockStore } from '../../stores/stockStore'
import { dataFreshness } from '../../composables/useDataFreshness'
import { useCostLineCalculations } from '../../composables/useCostLineCalculations'
import { useCostLineAutosave } from '../../composables/useCostLineAutosave'
import { usePhantomRow } from '../../composables/usePhantomRow'
import {
  gridCellAttrs,
  handleGridCellKeydown,
  useGridKeyboardNav,
} from '../../composables/useGridKeyboardNav'
import { costlineService } from '../../services/costline.service'
import { jobService } from '../../services/job.service'
import {
  labourItemId,
  nextLabourDesc,
  parseLabourItemId,
  rateForSubtype,
  subtypeName,
  workshopRateEntry,
  type JobLabourRate,
} from '../../utils/labourRates'

import { schemas } from '../../api/generated/api'
import type { z } from 'zod'

// Types from generated schemas
// Extend CostLine type to include timestamp fields (to be added to backend schema)
type CostLine = z.infer<typeof schemas.CostLine> & {
  created_at?: string
  updated_at?: string
}
type PatchedCostLineCreateUpdate = z.infer<typeof schemas.PatchedCostLineCreateUpdateRequest>

type TabKind = 'estimate' | 'quote' | 'actual'
export type KindOption = 'material' | 'time' | 'adjust'

// Row context helper (DataTable passes TanStack context with row)
type RowCtx = DataTableRowContext & { row: { index: number } }

const props = withDefaults(
  defineProps<{
    lines: CostLine[]
    tabKind: TabKind
    readOnly?: boolean
    showItemColumn?: boolean
    showSourceColumn?: boolean
    // Resolver for "Source" column (read-only). If not provided, Source column will be hidden or blank.
    sourceResolver?: (
      line: CostLine,
    ) => { visible: boolean; label: string; onClick?: () => void } | null
    // Limit available kinds for dropdown
    allowedKinds?: KindOption[]
    // Block specific fields by kind (e.g., for 'actual' tab material lines until stock selected)
    blockedFieldsByKind?: Record<KindOption, string[]>
    // For 'actual' tab: Function to call on stock selection for new lines
    consumeStockFn?: (payload: {
      line: CostLine
      stockId: string
      quantity: number
      unitCost: number
      unitRev: number
    }) => Promise<void>
    // Job ID for consumption context
    jobId?: string
    negativeStockIds?: string[]
  }>(),
  {
    readOnly: false,
    showItemColumn: true,
    showSourceColumn: false,
    allowedKinds: () => ['material', 'time', 'adjust'],
    blockedFieldsByKind: () => ({ material: [], time: [], adjust: [] }),
    negativeStockIds: () => [],
  },
)

const emit = defineEmits<{
  'delete-line': [idOrIndex: string | number]
  'duplicate-line': [line: CostLine]
  'move-line': [index: number, direction: 'up' | 'down']
  'create-line': [line: CostLine]
}>()

// UI state
const selectedRowIndex = ref<number>(-1)
const containerRef = ref<HTMLElement | null>(null)
const showShortcuts = ref(false)
const openItemSelect = ref(false)
const approvingId = ref<string | null>(null)

// Local UI-only mapping: selected Item data per line (not persisted)
const selectedItemMap = new WeakMap<
  CostLine,
  { id: string; description: string; item_code?: string } | null
>()

const createdOnce = new WeakSet<CostLine>()

/**
 * Ensure there's always at least one empty line for editing
 */
function makeEmptyLine(kind: KindOption = 'material'): CostLine {
  return {
    id: '',
    kind,
    desc: '',
    quantity: 1,
    unit_cost: undefined,
    unit_rev: undefined,
    ext_refs: {},
    meta: {},
    total_cost: 0,
    created_at: '',
    updated_at: '',
    accounting_date: '',
    total_rev: 0,
    labour_subtype: null,
  }
}

const {
  phantomRow: emptyLine,
  displayRows: displayLines,
  resetPhantom,
  selectPhantom,
} = usePhantomRow<CostLine>({
  rows: () => props.lines,
  makePhantom: makeEmptyLine,
})

function selectEmptyLine(): void {
  selectPhantom((index) => (selectedRowIndex.value = index))
}

const negativeIdsSig = computed(() => props.negativeStockIds?.slice().sort().join('|') || '')

function resetEmptyLine(kind: KindOption = 'material') {
  debugLog('resetEmptyLine called with kind:', kind)
  resetPhantom(makeEmptyLine(kind))
}

function maybeEmitCreate(line: CostLine) {
  if (createdOnce.has(line)) return
  createdOnce.add(line)

  const payload = line
  debugLog('SmartCostLinesTable emitting event: create-line', payload)
  emit('create-line', payload)

  if (line === emptyLine.value) resetEmptyLine()
}

function updateLineKind(line: CostLine, newKind: KindOption) {
  if (String(line.kind) === newKind) return

  if (newKind === 'time') {
    // Time lines need the company wage rate as unit_cost. If defaults haven't
    // loaded yet, abort BEFORE mutating kind so the line stays in its prior
    // kind (tryCompanyWageRate toasts on the null case).
    const wage = tryCompanyWageRate()
    if (wage === null) return

    Object.assign(line, { kind: newKind })

    // Time lines require a labour subtype; default to the workshop subtype.
    // unit_cost from company wage rate, unit_rev from the job's subtype rate.
    // If the labour-rates fetch hasn't resolved yet, subtypeId stays null and
    // the backend rejects the save with a visible validation error —
    // deliberately no frontend pre-guard, so a broken rates endpoint can't
    // silently disable time lines.
    const subtypeId =
      line.labour_subtype ?? workshopRateEntry(jobLabourRates.value)?.labour_subtype ?? null
    Object.assign(line, {
      labour_subtype: subtypeId,
      unit_cost: wage,
      unit_rev: rateForSubtype(jobLabourRates.value, subtypeId),
    })
  } else {
    Object.assign(line, { kind: newKind })
    Object.assign(line, { labour_subtype: null })
    if (line.unit_cost !== undefined && line.unit_cost !== null) {
      // Recalculate unit_rev with markup for material/adjust
      const derived = apply(line).derived
      Object.assign(line, { unit_rev: derived.unit_rev })
    } else {
      // Mid-entry row (e.g. phantom row where the user typed a description
      // first): no unit_cost yet, so unit_rev cannot be derived. It is
      // derived when the user enters unit_cost.
    }
  }

  // Save if line has real ID and meets baseline
  if (line.id && isLineReadyForSave(line)) {
    debugLog('Saving kind change:', line.id, newKind)
    const patch: PatchedCostLineCreateUpdate = {
      kind: newKind,
      labour_subtype: line.labour_subtype ?? null,
      ...(newKind === 'time'
        ? {
            unit_cost: requiredNumber(line.unit_cost, 'cost line unit_cost'),
            unit_rev: requiredNumber(line.unit_rev, 'cost line unit_rev'),
          }
        : { unit_rev: requiredNumber(line.unit_rev, 'cost line unit_rev') }),
    }
    const optimistic: Partial<CostLine> = { ...patch }
    autosave.scheduleSave(line, patch, optimistic)
  }
}

/**
 * A labour subtype was picked in the Item cell: turn the line into a time
 * line for that subtype in one mutation + one durable save.
 */
async function handleLabourPicked(line: CostLine, subtypeId: string) {
  const rate = jobLabourRates.value.find((r) => r.labour_subtype === subtypeId)
  if (!rate) {
    // Picker options come from jobLabourRates, so a miss is a bug: crash
    // rather than save a line with rates we cannot resolve.
    throw new Error(`Labour subtype not found in job labour rates: ${subtypeId}`)
  }

  // Time lines need the company wage rate as unit_cost; abort the conversion
  // (leaving the line untouched) if defaults haven't loaded yet.
  const wage = tryCompanyWageRate()
  if (wage === null) return

  // Re-prefill unit_rev from the job's rate for the chosen subtype; the user
  // can still override it afterwards (consistent with item selection).
  resetUnitRevOverride(line)

  // Material → labour conversion drops the stock reference.
  const extRefs = { ...((line.ext_refs as Record<string, unknown>) || {}) }
  delete extRefs.stock_id

  Object.assign(line, {
    kind: 'time' as const,
    labour_subtype: subtypeId,
    desc: nextLabourDesc(line.desc || '', rate, jobLabourRates.value),
    unit_cost: wage,
    unit_rev: rateForSubtype(jobLabourRates.value, subtypeId),
    ext_refs: extRefs,
    quantity: line.quantity ?? 1,
  })
  selectedItemMap.set(line, null)

  if (!line.id) {
    maybeEmitCreate(line)
    return
  }

  // Explicit subtype selection should be durable before the UI moves on.
  const patch: PatchedCostLineCreateUpdate = {
    kind: 'time',
    labour_subtype: subtypeId,
    desc: line.desc || '',
    unit_cost: requiredNumber(line.unit_cost, 'cost line unit_cost'),
    unit_rev: requiredNumber(line.unit_rev, 'cost line unit_rev'),
    ext_refs: extRefs,
  }
  const optimistic: Partial<CostLine> = { ...patch } as Partial<CostLine>
  await autosave.saveNow(line, patch, optimistic)
}

// Company Defaults and calculations
const companyDefaultsStore = useCompanyDefaultsStore()
const store = useStockStore()

/**
 * Time-line conversion needs the company wage rate as the line's unit_cost.
 * Before company defaults have loaded `wage_rate` is null/undefined/'' — reading
 * it via requiredNumber would throw and crash the table on early interaction.
 * Return null (and toast) so callers can abort the conversion cleanly; never
 * fall back to a fabricated wage number.
 */
function tryCompanyWageRate(): number | null {
  const wageRate = companyDefaultsStore.companyDefaults?.wage_rate
  if (wageRate === null || wageRate === undefined || wageRate === ('' as unknown)) {
    toast.error('Company defaults are still loading. Please try again.')
    return null
  }
  return requiredNumber(wageRate, 'company defaults wage_rate')
}

function companyMaterialsMarkup(): number {
  return requiredNumber(
    companyDefaultsStore.companyDefaults?.materials_markup,
    'company defaults materials_markup',
  )
}

// Job's per-labour-subtype charge-out rates: drives time-line unit_rev and the
// labour subtype dropdown options.
const jobLabourRates = ref<JobLabourRate[]>([])
const jobLabourRatesLoaded = ref(false)

onMounted(() => {
  if (!companyDefaultsStore.isLoaded && !companyDefaultsStore.isLoading) {
    companyDefaultsStore.loadCompanyDefaults()
  }
  // Ensure stock is loaded for item lookup
  if (store.items.length === 0 && !store.loading) {
    store.fetchStock()
  }
  if (props.jobId) {
    jobService
      .getJobLabourRates(props.jobId)
      .then((rates) => {
        jobLabourRates.value = rates
        jobLabourRatesLoaded.value = true
      })
      .catch((error) => {
        console.error('Failed to load job labour rates:', error)
        toast.error('Failed to load labour rates for this job')
      })
  }
})

const {
  apply,
  validateLine,
  isUnitCostEditable,
  isUnitRevenueEditable,
  onUnitRevenueManuallyEdited,
  onItemSelected,
  resetUnitRevOverride,
} = useCostLineCalculations({
  getCompanyDefaults: () => companyDefaultsStore.companyDefaults,
  getTimeChargeOutRate: (line) => rateForSubtype(jobLabourRates.value, line.labour_subtype),
})

// Autosave
const autosave = useCostLineAutosave({
  debounceMs: 600, // within spec 400–800ms
  statusSource: 'smart-cost-lines',
  saveFn: async (id: string, patch: PatchedCostLineCreateUpdate) => {
    const updated = await costlineService.updateCostLine(id, patch)
    // Return the updated line so timestamps can be synced
    return updated
  },
  onOptimisticApply: (line, patch) => {
    // Mutate in-place to propagate to parent summaries (objects are shared by reference)
    Object.assign(line, patch as Partial<CostLine>)
  },
  onRollback: (line, snap) => {
    Object.assign(line, snap)
    toast.error('Failed to save changes. Restored previous values.')
  },
})

onUnmounted(() => {
  autosave.clearStatus()
})

/**
 * Helpers
 */
function getKindBadge(line: CostLine) {
  const kind = String(line.kind)
  switch (kind) {
    case 'time':
      return { label: 'Labour', class: 'bg-blue-100 text-blue-800' }
    case 'material':
      return { label: 'Material', class: 'bg-green-100 text-green-800' }
    case 'adjust':
      return { label: 'Adjustment', class: 'bg-pink-100 text-pink-800' }
    default:
      return { label: kind, class: 'bg-gray-100 text-gray-800' }
  }
}

function formatModifiedDate(dateString: string): string {
  const date = new Date(dateString)
  const day = date.getDate().toString().padStart(2, '0')
  const month = date.toLocaleDateString('en-NZ', { month: 'short' }).toUpperCase()
  const year = date.getFullYear().toString().slice(-2)
  return `${day}/${month}/${year}`
}

function isDeliveryReceipt(line: CostLine): boolean {
  return !!(line?.meta && (line.meta as Record<string, string>).source === 'delivery_receipt')
}

function isStockLine(line: CostLine): boolean {
  return !!(line?.ext_refs && (line.ext_refs as Record<string, unknown>).stock_id)
}

function isUnapproved(line: CostLine): boolean {
  return line?.approved === false
}

function isNegativeStock(line: CostLine): boolean {
  if (!line?.id || !isStockLine(line)) return false
  const stockId = (line.ext_refs as Record<string, unknown>)?.stock_id
  console.log(
    'DEBUG: isNegativeStock - stockId:',
    stockId,
    'type:',
    typeof stockId,
    'negativeStockIds:',
    props.negativeStockIds,
  )
  return props.negativeStockIds?.includes(stockId as string) ?? false
}

function canEditField(
  line: CostLine,
  field: 'desc' | 'quantity' | 'unit_cost' | 'unit_rev',
): boolean {
  if (props.readOnly) return false

  if (isDeliveryReceipt(line)) return false

  const kind = String(line.kind)
  if (field === 'unit_cost') {
    return isUnitCostEditable(line)
  }
  if (field === 'unit_rev') {
    return isUnitRevenueEditable(line)
  }
  if (field === 'quantity' && props.tabKind === 'actual') {
    // For actuals, quantity on non-adjust lines typically should not be edited (origin = system)
    const isMaterial = kind === 'material'
    const isConsumed =
      !!line.id || !!(line.ext_refs && (line.ext_refs as Record<string, unknown>).stock_id)
    return kind === 'adjust' || (isMaterial && isConsumed)
  }
  if (field === 'desc' && props.tabKind === 'actual') {
    // only allow description editing for adjustments and materials
    return kind === 'adjust' || kind === 'material'
  }

  // desc & quantity in non-actual tabs
  return true
}

/**
 * Check if line meets baseline criteria for saving:
 * - Has description
 * - Has quantity > 0
 * - Has unit_cost and unit_rev (even if auto-calculated)
 */
function isLineReadyForSave(line: CostLine): boolean {
  if (!line.desc || line.desc.trim() === '') return false
  const quantity = Number(line.quantity)
  if (!Number.isFinite(quantity) || quantity <= 0) return false
  if (line.unit_cost === undefined || line.unit_cost === null) return false
  if (line.unit_rev === undefined || line.unit_rev === null) return false
  return true
}

function isIncompleteNewLine(line: CostLine): boolean {
  return !line.id && !isLineReadyForSave(line)
}

function canRenderDerivedValues(line: CostLine): boolean {
  if (isIncompleteNewLine(line)) return false
  if (line.unit_cost === undefined || line.unit_cost === null) return false
  if (line.unit_rev === undefined || line.unit_rev === null) return false
  if (String(line.kind) === 'time' && !jobLabourRatesLoaded.value) return false
  return true
}

/**
 * Keyboard navigation
 */
const { onKeydown } = useGridKeyboardNav({
  getRowCount: () => displayLines.value.length,
  getSelectedIndex: () => selectedRowIndex.value,
  setSelectedIndex: (i) => (selectedRowIndex.value = i),

  startEdit: () => {
    // No-op here; inputs are directly focusable. Could focus first editable input in selected row if needed.
  },
  commitEdit: () => {
    // Inputs save on blur; pressing Enter can just move focus outward (handled by browser).
  },
  cancelEdit: () => {
    // No stateful edit buffers here; UI uses immediate binding. Intentionally no-op.
  },

  addLine: selectEmptyLine,
  duplicateSelected: () => {
    const i = selectedRowIndex.value
    if (i >= 0 && i < displayLines.value.length) {
      const line = displayLines.value[i]
      // Only duplicate actual lines, not auto-generated empty ones
      if (line.id || props.lines.includes(line)) {
        debugLog('SmartCostLinesTable emitting event: duplicate-line', line)
        emit('duplicate-line', line)
      }
    }
  },
  deleteSelected: () => {
    const i = selectedRowIndex.value
    debugLog('Keyboard delete triggered for selectedRowIndex:', i)

    if (i >= 0 && i < displayLines.value.length) {
      const line = displayLines.value[i]
      debugLog('Keyboard delete for line:', {
        lineId: line.id,
        selectedIndex: i,
        lineDesc: line.desc,
        isLocalLine: !line.id,
      })

      if (line.id) {
        debugLog('Keyboard emitting delete-line with line.id:', line.id)
        autosave.cancel(line)
        emit('delete-line', line.id as string)
      } else {
        // Find the actual index in the original props.lines array
        const actualIndex = props.lines.findIndex((l) => l === line)
        debugLog('Keyboard looking for local line in props.lines:', {
          actualIndex,
          foundLine: actualIndex >= 0 ? props.lines[actualIndex] : null,
        })

        if (actualIndex >= 0) {
          debugLog('Keyboard emitting delete-line with actualIndex:', actualIndex)
          autosave.cancel(line)
          emit('delete-line', actualIndex)
        } else {
          debugLog('Keyboard: Auto-generated empty line - cannot delete, ignoring')
        }
      }
    }
  },
  moveSelectedUp: () => {
    const i = selectedRowIndex.value
    if (i > 0) emit('move-line', i, 'up')
  },
  moveSelectedDown: () => {
    const i = selectedRowIndex.value
    if (i >= 0 && i < displayLines.value.length - 1) emit('move-line', i, 'down')
  },
})

function handleCellNav(e: KeyboardEvent, rowIndex: number, columnId: string): boolean {
  return handleGridCellKeydown(e, {
    container: containerRef.value,
    rowIndex,
    columnId,
  })
}

function handleRowClick(line: CostLine, index: number) {
  selectedRowIndex.value = index
}

async function approveLine(line: CostLine) {
  if (!line.id || approvingId.value) return

  const toastId = `approve-line-${line.id}`
  approvingId.value = String(line.id)
  toast.info('Approving line...', { id: toastId })

  try {
    const updated = await costlineService.approveCostLine(String(line.id))
    Object.assign(line, updated)
    toast.success('Line approved', { id: toastId })
  } catch (error) {
    console.error('Failed to approve cost line:', error)
    toast.error('Failed to approve line', { id: toastId })
  } finally {
    approvingId.value = null
  }
}

const shortcutsTitle = computed(
  () =>
    'Shortcuts: Enter/F2 edit • Enter confirm • Esc cancel • Tab/Shift+Tab move • ↑/↓ row • Ctrl/Cmd+Enter add • Ctrl/Cmd+D duplicate • Ctrl/Cmd+Backspace delete • Alt+↑/↓ move row',
)

/**
 * Build the column defs for DataTable
 */
const columns = computed(() => {
  void negativeIdsSig.value
  return [
    // Type / Kind - Now readonly badge only
    {
      id: 'kind',
      header: 'Type',
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        const badge = getKindBadge(line)
        const pending = isUnapproved(line)
        return h('div', { class: 'flex flex-col gap-1' }, [
          h(Badge, { class: `text-xs font-medium ${badge.class}` }, () => badge.label),
          ...(pending
            ? [
                h(
                  Badge,
                  {
                    variant: 'outline',
                    class:
                      'text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200',
                  },
                  () => 'Pending approval',
                ),
              ]
            : []),
        ])
      },
      meta: { editable: false }, // Always readonly
    },

    // Item
    props.showItemColumn
      ? {
          id: 'item',
          header: () => h('div', { class: 'col-item text-left' }, 'Item'),
          cell: ({ row }: RowCtx) => {
            const line = displayLines.value[row.index]
            const selectedItem = selectedItemMap.get(line)
            const kind = String(line.kind)
            const isTime = kind === 'time'
            // Time lines derive their picker value from labour_subtype, so
            // loaded lines resolve without selectedItemMap or the stock store.
            const model = isTime
              ? line.labour_subtype
                ? labourItemId(line.labour_subtype)
                : null
              : selectedItem?.id ||
                ((line.ext_refs as Record<string, unknown>)?.stock_id as string) ||
                null
            const isMaterial = kind === 'material'
            const isNewLine = !line.id
            const isActualTab = props.tabKind === 'actual'

            const lockedByDeliveryReceipt = isDeliveryReceipt(line)
            // Only lock existing stock lines on actual tab (where inventory is consumed)
            // Estimate/quote tabs should allow changing material selection
            const lockedStockExisting = isActualTab && !!line.id && isStockLine(line)
            // Time lines are re-pickable on estimate/quote (changing subtype =
            // re-pick); on the actual tab their subtype is edited in the
            // timesheet UI only.
            const enabled =
              !(isTime && isActualTab) &&
              !props.readOnly &&
              !lockedByDeliveryReceipt &&
              !lockedStockExisting

            const isActive = selectedRowIndex.value === row.index

            // Lazy mount: render lightweight control until row is active (selected)
            if (!isActive) {
              const labourLabel = subtypeName(jobLabourRates.value, line.labour_subtype) ?? 'Labour'

              // Actual tab time lines: read-only blue text, not a button.
              if (isTime && isActualTab) {
                return h(
                  'div',
                  {
                    class: 'col-item flex items-center',
                    'data-automation-id': `SmartCostLinesTable-item-${row.index}`,
                  },
                  [h('span', { class: 'text-sm font-medium text-blue-800' }, labourLabel)],
                )
              }

              return h(
                'div',
                {
                  class: 'col-item flex items-center',
                  'data-automation-id': `SmartCostLinesTable-item-${row.index}`,
                },
                [
                  h(
                    Button,
                    {
                      variant: 'outline',
                      size: 'sm',
                      disabled: !enabled,
                      onClick: (e: Event) => {
                        e.stopPropagation()
                        selectedRowIndex.value = row.index
                        // Also open the ItemSelect dropdown immediately
                        openItemSelect.value = true
                      },
                      class: isTime
                        ? 'text-blue-800 font-medium'
                        : 'font-mono uppercase tracking-wide',
                    },
                    () => {
                      if (isTime) {
                        return labourLabel
                      }

                      if (!model) {
                        const stockId = (line.ext_refs as Record<string, unknown>)
                          ?.stock_id as string
                        // Check if this is an existing line with stock selected
                        if (stockId) {
                          // Try to find the item in the stock store by ID
                          const stockItem = store.items.find((item) => item.id === stockId)
                          if (stockItem?.item_code) {
                            return stockItem.item_code
                          }
                        }

                        // If no stock_id or item not found by ID, try to find by description
                        if (line.desc) {
                          const stockItemByDesc = store.items.find(
                            (item) => item.description?.toLowerCase() === line.desc?.toLowerCase(),
                          )
                          if (stockItemByDesc?.item_code) {
                            return stockItemByDesc.item_code
                          }
                        }

                        // If no valid item found, prompt user to select a valid item
                        return 'Select Item'
                      }

                      // If we have selectedItem, use its code
                      if (selectedItem?.item_code) {
                        return selectedItem.item_code
                      }

                      // If no selectedItem but we have a model (stock_id), find the item in store
                      if (model) {
                        const stockItem = store.items.find((item) => item.id === model)
                        if (stockItem?.item_code) {
                          return stockItem.item_code
                        }
                      }

                      return 'Change item'
                    },
                  ),
                ],
              )
            }

            return h(
              'div',
              { class: 'col-item', 'data-automation-id': `SmartCostLinesTable-item-${row.index}` },
              [
                h(ItemSelect, {
                  modelValue: model,
                  open: openItemSelect.value,
                  'onUpdate:open': async (val: boolean) => {
                    openItemSelect.value = val
                    if (!val) return
                    // Picker open is the moment the user is about to lock in a
                    // unit cost. Check the backend stock dataset version; if it
                    // changed since this session loaded, the subscribed callback
                    // in stockStore clears the cache so the follow-up
                    // fetchStock() pulls fresh prices before the user picks.
                    try {
                      await dataFreshness.checkFreshness()
                    } catch {
                      // Non-fatal; fall through to fetchStock which will hit
                      // the cache or the network as usual.
                    }
                    if (store.items.length === 0 && !store.loading) {
                      void store.fetchStock()
                    }
                  },
                  disabled: !enabled,
                  lineKind: String(line.kind),
                  tabKind: props.tabKind,
                  labourRates: jobLabourRates.value,
                  onClick: (e: Event) => e.stopPropagation(),
                  'onUpdate:modelValue': async (val: string | null) => {
                    if (!enabled) return

                    // Labour pick: handled in one place, before any
                    // kind-inference / stock-store lookup, so updateLineKind's
                    // save never fires for picker-driven labour (no
                    // double-save) and the stock-miss branch can't wipe desc.
                    const labourSubtypeId = parseLabourItemId(val)
                    if (labourSubtypeId) {
                      // Leave active mode to show the subtype chip
                      selectedRowIndex.value = -1
                      await handleLabourPicked(line, labourSubtypeId)
                      return
                    }

                    if (val) {
                      debugLog('Storing item selection:', { val, lineId: line.id })
                      // For regular items, we'll fetch the data below and update
                      selectedItemMap.set(line, { id: val, description: '', item_code: '' })
                      debugLog('Stored placeholder for stock item in selectedItemMap')
                    } else {
                      selectedItemMap.set(line, null)
                      debugLog('Cleared selectedItemMap for line')
                    }

                    // Infer kind based on selection
                    const newKind: KindOption = val ? 'material' : 'adjust'

                    // Update kind if it changed
                    if (String(line.kind) !== newKind) {
                      updateLineKind(line, newKind)
                    }

                    onItemSelected(line)

                    if (
                      isActualTab &&
                      isNewLine &&
                      isMaterial &&
                      val &&
                      props.consumeStockFn &&
                      props.jobId
                    ) {
                      try {
                        // Look up stock item from store (already loaded for the dropdown)
                        const stock = store.items.find((item) => item.id === val)
                        if (!stock) {
                          throw new Error('Stock item not found in store')
                        }
                        const qty = requiredNumber(line.quantity, 'cost line quantity')
                        const unitCost = requiredNumber(
                          stock.unit_cost,
                          `unit_cost for stock ${stock.id}`,
                        )
                        const markup = companyMaterialsMarkup()
                        const unitRev = roundToDecimalPlaces(unitCost * (1 + markup), 2)
                        await props.consumeStockFn({
                          line,
                          stockId: val,
                          quantity: qty,
                          unitCost,
                          unitRev,
                        })

                        // to leave the active mode and show the chip/label instead of "Select Item"
                        selectedRowIndex.value = -1
                      } catch {
                        toast.error('Failed to consume stock. Line not created.')
                        selectedItemMap.set(line, null)
                        return
                      }
                    } else {
                      // For other tabs (quote, estimate), also leave active mode to show item code
                      selectedRowIndex.value = -1
                    }

                    // Look up stock item from store (already loaded for the dropdown)
                    const found = val ? store.items.find((item) => item.id === val) : null
                    if (found) {
                      debugLog('Found stock item in store:', {
                        id: found.id,
                        item_code: found.item_code,
                        description: found.description,
                      })
                      const stockUnitCost = requiredNumber(
                        found.unit_cost,
                        `unit_cost for stock ${found.id}`,
                      )
                      const stockUnitRevenue =
                        found.unit_revenue === null || found.unit_revenue === undefined
                          ? null
                          : requiredNumber(found.unit_revenue, `unit_revenue for stock ${found.id}`)
                      Object.assign(line, { desc: found.description || '' })
                      Object.assign(line, { unit_cost: stockUnitCost })
                      // Update ext_refs.stock_id to reference the selected item
                      Object.assign(line, {
                        ext_refs: { ...((line.ext_refs as object) || {}), stock_id: val },
                      })
                      // Update selectedItemMap with full data
                      selectedItemMap.set(line, {
                        id: val as string,
                        description: found.description || '',
                        item_code: found.item_code || '',
                      })
                      debugLog('Updated line with stock item data:', {
                        id: val,
                        description: found.description || '',
                        item_code: found.item_code || '',
                      })
                      // Ensure quantity is set for new lines
                      if (line.quantity == null) Object.assign(line, { quantity: 1 })
                      if (kind !== 'time') {
                        if (stockUnitRevenue !== null) {
                          Object.assign(line, { unit_rev: stockUnitRevenue })
                          onUnitRevenueManuallyEdited(line)
                        } else {
                          Object.assign(line, { unit_rev: apply(line).derived.unit_rev })
                        }
                      }

                      // For phantom rows (no ID), emit create-line if ready after fetch
                      if (!line.id && isLineReadyForSave(line)) {
                        // Use guarded emitter so the phantom row resets and does not duplicate
                        maybeEmitCreate(line)
                      }
                    } else if (val) {
                      debugLog('Stock item not found in store for id:', val)
                      Object.assign(line, { desc: '' })
                      Object.assign(line, { unit_cost: 0 })
                      selectedItemMap.set(line, null)
                    }

                    // Explicit item replacement should be durable before the UI moves on.
                    if (line.id && isLineReadyForSave(line)) {
                      const patch: PatchedCostLineCreateUpdate = {
                        desc: line.desc || '',
                        unit_cost: requiredNumber(line.unit_cost, 'cost line unit_cost'),
                        unit_rev: requiredNumber(line.unit_rev, 'cost line unit_rev'),
                        ext_refs: { stock_id: val },
                      }
                      const optimistic: Partial<CostLine> = { ...patch }
                      await autosave.saveNow(line, patch, optimistic)
                    }
                  },
                  // Labour picks manage desc in handleLabourPicked (which can
                  // preserve user-authored text); this assign is stock-only.
                  'onUpdate:description': (desc: string) =>
                    enabled && String(line.kind) !== 'time' && Object.assign(line, { desc }),
                  'onUpdate:unit_cost': (cost: number | null) => {
                    if (!enabled) return
                    if (cost === null) {
                      Object.assign(line, { unit_cost: null })
                      return
                    }
                    Object.assign(line, {
                      unit_cost: requiredNumber(cost, 'cost line unit_cost'),
                    })
                    if (kind !== 'time')
                      Object.assign(line, { unit_rev: apply(line).derived.unit_rev })
                    nextTick(() => {
                      if (!line.id && isLineReadyForSave(line)) maybeEmitCreate(line)
                    })
                  },
                  'onUpdate:kind': (newKind: string | null) => {
                    if (!enabled || !newKind) return
                    updateLineKind(line, newKind as KindOption)
                  },
                }),
              ],
            )
          },
          meta: { editable: !props.readOnly },
        }
      : null,

    // Description
    {
      id: 'desc',
      header: () => h('div', { class: 'desc-col text-left' }, 'Description'),
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        const kind = String(line.kind)
        const isNewLine = !line.id
        const isActualTab = props.tabKind === 'actual'
        const blockedFields = props.blockedFieldsByKind?.[kind as KindOption] || []
        const isFieldBlocked = blockedFields.includes('desc')
        const hasStockSelected = !!selectedItemMap.get(line)
        const isBlocked =
          isActualTab && isNewLine && kind === 'material' && isFieldBlocked && !hasStockSelected
        const canEdit = canEditField(line, 'desc') && !isBlocked

        return h('div', { class: 'desc-cell w-full flex items-start gap-2' }, [
          h(Textarea, {
            modelValue: line.desc || '',
            disabled: !canEdit,
            class: 'w-full min-h-[2.25rem] text-sm',
            rows: 1,
            ...gridCellAttrs(row.index, 'desc'),
            onClick: (e: Event) => {
              // Stop propagation to grid; fully inline editing
              e.stopPropagation()
            },
            onKeydown: (e: KeyboardEvent) => {
              const ctrlOrCmd = e.metaKey || e.ctrlKey
              if (handleCellNav(e, row.index, 'desc')) return
              if (e.key === 'Enter' && ctrlOrCmd) {
                e.preventDefault()
                e.stopPropagation()
                selectEmptyLine()
                return
              }
              // Allow line breaks in textarea and prevent bubbling to the grid
              e.stopPropagation()
            },
            'onUpdate:modelValue': (v: string | number) => {
              const val = typeof v === 'string' ? v : String(v)
              Object.assign(line, { desc: val })
              // Infer "adjust" when user starts typing without a selected item
              const hasSelectedItemLocal = !!selectedItemMap.get(line)
              const isLabour = line.kind === 'time'
              const isAdjust = line.kind === 'adjust'
              if (!hasSelectedItemLocal && val.trim() && !isAdjust && !isLabour) {
                updateLineKind(line, 'adjust')
              }
            },
            onBlur: () => {
              if (!canEdit) return
              // Create from phantom row if baseline is satisfied
              if (!line.id && isLineReadyForSave(line)) {
                maybeEmitCreate(line)
                return
              }
              // Save inline for existing lines
              if (!line.id || !isLineReadyForSave(line)) return
              const patch: PatchedCostLineCreateUpdate = { desc: line.desc || '' }
              const optimistic: Partial<CostLine> = { desc: line.desc || '' }
              autosave.onBlurSave(line, patch, optimistic)
            },
          }),
          ...(isBlocked
            ? [
                h(
                  Badge,
                  { variant: 'secondary', class: 'mt-1 text-xs' },
                  () => 'Select stock first',
                ),
              ]
            : []),
        ])
      },
    },

    // Quantity
    {
      id: 'quantity',
      header: () => h('div', { class: 'col-8ch text-center' }, 'Quantity'),
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        const kind = String(line.kind)
        const isNewLine = !line.id
        const isActualTab = props.tabKind === 'actual'
        const blockedFields = props.blockedFieldsByKind?.[kind as KindOption] || []
        const isFieldBlocked = blockedFields.includes('quantity')
        const hasStockSelected = !!selectedItemMap.get(line)
        const isBlocked =
          isActualTab && isNewLine && kind === 'material' && isFieldBlocked && !hasStockSelected

        return [
          h('div', { class: 'col-10ch' }, [
            h(Input, {
              type: 'number',
              step: String(kind === 'time' ? 0.25 : 1),
              ...(kind === 'adjust' ? {} : { min: '0.0000001' }),
              modelValue: line.quantity,
              disabled: !canEditField(line, 'quantity') || isBlocked,
              class: 'w-full text-right numeric-input',
              inputmode: 'decimal',
              'data-automation-id': `SmartCostLinesTable-quantity-${row.index}`,
              ...gridCellAttrs(row.index, 'quantity'),
              onClick: (e: Event) => e.stopPropagation(),
              onKeydown: (e: KeyboardEvent) => handleCellNav(e, row.index, 'quantity'),
              'onUpdate:modelValue': (val: string | number) => {
                const num = Number(val)
                if (!Number.isNaN(num)) Object.assign(line, { quantity: num })
              },
              onBlur: () => {
                const validation = validateLine(line)
                if (!validation.isValid) {
                  toast.error(validation.issues[0]?.message || 'Invalid quantity')
                  return
                }
                if (!line.id && isLineReadyForSave(line)) {
                  maybeEmitCreate(line)
                  return
                }
                if (!line.id || !isLineReadyForSave(line)) return
                const qtyNum = requiredNumber(line.quantity, 'cost line quantity')
                const patch: PatchedCostLineCreateUpdate = { quantity: qtyNum }
                const optimistic: Partial<CostLine> = { quantity: qtyNum }
                autosave.onBlurSave(line, patch, optimistic)
              },
            }),
          ]),
          ...(isBlocked
            ? [
                h(
                  Badge,
                  { variant: 'secondary', class: 'mt-1 text-xs' },
                  () => 'Select stock first',
                ),
              ]
            : []),
        ]
      },
    },

    // Unit Cost
    {
      id: 'unit_cost',
      header: () => h('div', { class: 'col-10ch text-center' }, 'Unit Cost'),
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        const kind = String(line.kind)
        const isNewLine = !line.id
        const isActualTab = props.tabKind === 'actual'
        const blockedFields = props.blockedFieldsByKind?.[kind as KindOption] || []
        const isFieldBlocked = blockedFields.includes('unit_cost')
        const hasStockSelected = !!selectedItemMap.get(line)
        const isBlocked =
          isActualTab && isNewLine && kind === 'material' && isFieldBlocked && !hasStockSelected
        const editable = canEditField(line, 'unit_cost') && !isBlocked
        const isTime = kind === 'time'
        const resolved = canRenderDerivedValues(line) ? apply(line).derived : null
        return [
          h('div', { class: 'col-10ch' }, [
            h(Input, {
              type: 'number',
              step: '0.01',
              min: '0',
              modelValue: isTime
                ? (line.unit_cost ?? resolved?.unit_cost ?? '')
                : (line.unit_cost ?? ''),
              disabled: !editable,
              class: 'w-full text-right numeric-input',
              inputmode: 'decimal',
              'data-automation-id': `SmartCostLinesTable-unit-cost-${row.index}`,
              ...gridCellAttrs(row.index, 'unit_cost'),
              onClick: (e: Event) => e.stopPropagation(),
              onKeydown: (e: KeyboardEvent) => handleCellNav(e, row.index, 'unit_cost'),
              'onUpdate:modelValue': (val: string | number) => {
                if (!editable) return
                if (val === '') {
                  Object.assign(line, { unit_cost: null })
                  return
                } else {
                  const num = Number(val)
                  if (!Number.isNaN(num)) {
                    Object.assign(line, { unit_cost: num })

                    // Auto-recalculate unit_rev for material/adjust unless overridden
                    if (kind !== 'time') {
                      const derived = apply(line).derived
                      Object.assign(line, { unit_rev: derived.unit_rev })
                    }
                  }
                }
              },
              onBlur: () => {
                if (!editable) return

                // Create new line if it doesn't have an ID yet and meets baseline criteria
                if (!line.id && isLineReadyForSave(line)) {
                  debugLog('Creating new line from unit_cost edit:', line)
                  maybeEmitCreate(line)
                  return
                }

                if (!line.id || !isLineReadyForSave(line)) {
                  debugLog('Skipping unit_cost save:', {
                    editable,
                    id: line.id,
                    ready: isLineReadyForSave(line),
                  })
                  return
                }

                debugLog('Saving unit_cost change:', line.id, line.unit_cost)
                // For material/adjust, unit_rev may be auto recalculated unless overridden
                const derived = apply(line).derived
                const patch: PatchedCostLineCreateUpdate = {
                  unit_cost: requiredNumber(line.unit_cost, 'cost line unit_cost'),
                  ...(kind !== 'time'
                    ? { unit_rev: requiredNumber(derived.unit_rev, 'derived cost line unit_rev') }
                    : {}),
                }
                const optimistic: Partial<CostLine> = { ...patch }
                autosave.onBlurSave(line, patch, optimistic)
              },
            }),
          ]),
          ...(isBlocked
            ? [
                h(
                  Badge,
                  { variant: 'secondary', class: 'mt-1 text-xs' },
                  () => 'Select stock first',
                ),
              ]
            : []),
        ]
      },
    },

    // Unit Revenue
    {
      id: 'unit_rev',
      header: () => h('div', { class: 'col-10ch text-center' }, 'Unit Rev'),
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        const kind = String(line.kind)
        const isNewLine = !line.id
        const isActualTab = props.tabKind === 'actual'
        const blockedFields = props.blockedFieldsByKind?.[kind as KindOption] || []
        const isFieldBlocked = blockedFields.includes('unit_rev')
        const hasStockSelected = !!selectedItemMap.get(line)
        const isBlocked =
          isActualTab && isNewLine && kind === 'material' && isFieldBlocked && !hasStockSelected
        const editable = canEditField(line, 'unit_rev') && !isBlocked
        const isTime = kind === 'time'
        const resolved = canRenderDerivedValues(line) ? apply(line).derived : null
        return [
          h('div', { class: 'col-10ch' }, [
            h(Input, {
              type: 'number',
              step: '0.01',
              min: '0',
              modelValue: isTime
                ? (line.unit_rev ?? resolved?.unit_rev ?? '')
                : (line.unit_rev ?? ''),
              disabled: !editable,
              class: 'w-full text-right numeric-input',
              inputmode: 'decimal',
              'data-automation-id': `SmartCostLinesTable-unit-rev-${row.index}`,
              ...gridCellAttrs(row.index, 'unit_rev'),
              onClick: (e: Event) => e.stopPropagation(),
              'onUpdate:modelValue': (val: string | number) => {
                if (!editable) return
                if (val === '') {
                  Object.assign(line, { unit_rev: 0 })
                } else {
                  const num = Number(val)
                  if (!Number.isNaN(num)) {
                    Object.assign(line, { unit_rev: num })
                  }
                }
                // Mark override when user types in unit_rev
                onUnitRevenueManuallyEdited(line)
              },
              onKeydown: (e: KeyboardEvent) => {
                if (handleCellNav(e, row.index, 'unit_rev')) return
                if (
                  (e.key === 'Tab' || e.key === 'Enter') &&
                  row.index === displayLines.value.length - 1
                ) {
                  e.preventDefault()
                  if (isLineReadyForSave(line)) {
                    maybeEmitCreate(line)
                  }
                }
              },
              onBlur: () => {
                if (!editable) return

                // Create new line if it doesn't have an ID yet and meets baseline criteria
                if (!line.id && isLineReadyForSave(line)) {
                  debugLog('Creating new line from unit_rev edit:', line)
                  maybeEmitCreate(line)
                  return
                }

                if (!line.id || !isLineReadyForSave(line)) {
                  debugLog('Skipping unit_rev save:', {
                    editable,
                    id: line.id,
                    ready: isLineReadyForSave(line),
                  })
                  return
                }

                debugLog('Saving unit_rev change:', line.id, line.unit_rev)
                const patch: PatchedCostLineCreateUpdate = {
                  unit_rev: requiredNumber(line.unit_rev, 'cost line unit_rev'),
                }
                const optimistic: Partial<CostLine> = { unit_rev: patch.unit_rev }
                autosave.onBlurSave(line, patch, optimistic)
              },
            }),
          ]),
          ...(isBlocked
            ? [
                h(
                  Badge,
                  { variant: 'secondary', class: 'mt-1 text-xs' },
                  () => 'Select stock first',
                ),
              ]
            : []),
        ]
      },
    },

    // Total Cost
    {
      id: 'total_cost',
      header: () => h('div', { class: 'col-12ch text-center' }, 'Total Cost'),
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        if (!canRenderDerivedValues(line)) return h('div', { class: 'col-12ch' }, '')
        const qty = requiredNumber(line.quantity, 'cost line quantity')
        const unitCost =
          line.unit_cost !== null && line.unit_cost !== undefined
            ? line.unit_cost
            : apply(line).derived.unit_cost
        const umc = requiredNumber(unitCost, 'cost line unit_cost')
        const totalCost = String(line.kind) === 'time' ? qty * umc : qty * umc
        return h(
          'div',
          { class: 'col-12ch text-right font-medium numeric-text' },
          formatCurrency(totalCost),
        )
      },
      meta: { editable: false },
    },

    // Total Revenue
    {
      id: 'total_rev',
      header: () => h('div', { class: 'col-12ch text-center' }, 'Total Revenue'),
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        if (!canRenderDerivedValues(line)) return h('div', { class: 'col-12ch' }, '')
        const qty = requiredNumber(line.quantity, 'cost line quantity')
        const unitRev =
          line.unit_rev !== null && line.unit_rev !== undefined
            ? line.unit_rev
            : apply(line).derived.unit_rev
        const umr = requiredNumber(unitRev, 'cost line unit_rev')
        const totalRev = qty * umr
        return h(
          'div',
          { class: 'col-12ch text-right font-medium numeric-text' },
          formatCurrency(totalRev),
        )
      },
      meta: { editable: false },
    },

    // Source (optional)
    props.showSourceColumn
      ? {
          id: 'source',
          header: () => h('div', { class: 'source-col' }, 'Source'),
          cell: ({ row }: RowCtx) => {
            const line = displayLines.value[row.index]
            if (!props.sourceResolver)
              return h(
                'div',
                { class: 'source-cell text-gray-400 text-sm flex justify-center items-center' },
                '-',
              )
            const resolved = props.sourceResolver(line)
            if (!resolved || !resolved.visible)
              return h(
                'div',
                { class: 'source-cell flex justify-center items-center text-gray-400 text-sm' },
                '-',
              )

            const neg = isNegativeStock(line)
            return h('div', { class: 'source-cell flex flex-col gap-1 items-center' }, [
              h(
                'span',
                {
                  class:
                    'inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800 hover:bg-gray-200 cursor-pointer select-none truncate',
                  role: resolved.onClick ? 'button' : undefined,
                  tabindex: resolved.onClick ? 0 : -1,
                  onClick: resolved.onClick
                    ? () => resolved.onClick && resolved.onClick()
                    : undefined,
                  onKeydown: (e: KeyboardEvent) => {
                    if ((e.key === 'Enter' || e.key === ' ') && resolved.onClick) {
                      e.preventDefault()
                      resolved.onClick()
                    }
                  },
                  title: resolved.label,
                },
                resolved.label,
              ),
              ...(neg
                ? [
                    h(
                      'span',
                      {
                        class:
                          'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 border border-red-200 truncate',
                        title: 'Stock level for this item is negative',
                      },
                      [h(AlertTriangle, { class: 'w-3.5 h-3.5 mr-1' }), 'Negative'],
                    ),
                  ]
                : []),
            ])
          },
          meta: { editable: false },
        }
      : null,

    // Accounting Date - compact
    {
      id: 'accounting_date',
      header: () => h('div', { class: 'col-10ch text-center' }, 'Date'),
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        const mostRecentDate = line.accounting_date

        if (!mostRecentDate) {
          return h('div', { class: 'col-8ch text-left text-gray-400 text-xs' }, '-')
        }

        const formattedDate = formatModifiedDate(mostRecentDate)
        const fullDateTime = new Date(mostRecentDate).toLocaleString('en-NZ', {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })

        return h(
          'div',
          {
            class: 'col-10ch text-center text-gray-500 text-xs hover:text-gray-700',
            style: 'cursor: default;',
            title: `Full date/time: ${fullDateTime}`,
            onMouseenter: (e: MouseEvent) => {
              ;(e.target as HTMLElement).style.cursor = 'pointer'
            },
            onMouseleave: (e: MouseEvent) => {
              ;(e.target as HTMLElement).style.cursor = 'default'
            },
          },
          formattedDate,
        )
      },
      meta: { editable: false },
    },

    // Actions
    {
      id: 'actions',
      header: () => h('div', { class: 'w-full text-center' }, 'Actions'),
      cell: ({ row }: RowCtx) => {
        const line = displayLines.value[row.index]
        const approving = approvingId.value === line.id
        const disabled = !!props.readOnly || approving
        const canApprove =
          props.tabKind === 'actual' && !props.readOnly && !!line.id && isUnapproved(line)

        return h('div', { class: 'flex items-center justify-center w-full gap-2' }, [
          ...(canApprove
            ? [
                h(
                  Button,
                  {
                    variant: 'default',
                    size: 'icon',
                    class:
                      'h-8 w-8 bg-emerald-600 hover:bg-emerald-700 text-white flex items-center justify-center',
                    disabled: approving,
                    'aria-label': 'Approve line',
                    onClick: (e: Event) => {
                      e.stopPropagation()
                      if (approving) return
                      void approveLine(line)
                    },
                  },
                  () =>
                    approving
                      ? h('svg', { class: 'h-4 w-4 animate-spin', viewBox: '0 0 24 24' }, [
                          h('circle', {
                            class: 'opacity-25',
                            cx: '12',
                            cy: '12',
                            r: '10',
                            stroke: 'currentColor',
                            'stroke-width': '4',
                            fill: 'none',
                          }),
                          h('path', {
                            class: 'opacity-75',
                            fill: 'currentColor',
                            d: 'M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z',
                          }),
                        ])
                      : h(Check, { class: 'w-4 h-4 text-white' }),
                ),
              ]
            : []),
          h(
            Button,
            {
              variant: 'outline',
              size: 'icon',
              class:
                'h-8 w-8 text-red-600 hover:text-red-700 hover:bg-red-50 flex items-center justify-center',
              disabled,
              'aria-label': 'Delete line',
              'data-automation-id': `SmartCostLinesTable-delete-${row.index}`,
              onClick: (e: Event) => {
                e.stopPropagation()
                if (disabled) return

                debugLog('Delete button clicked for line:', {
                  lineId: line.id,
                  rowIndex: row.index,
                  lineDesc: line.desc,
                  isLocalLine: !line.id,
                  totalDisplayLines: displayLines.value.length,
                  totalPropsLines: props.lines.length,
                })

                // For local lines (no ID), delete immediately without confirmation
                if (!line.id) {
                  // Find the actual index in the original props.lines array
                  const actualIndex = props.lines.findIndex((l) => l === line)
                  debugLog('Looking for local line in props.lines:', {
                    actualIndex,
                    foundLine: actualIndex >= 0 ? props.lines[actualIndex] : null,
                    searchedLine: line,
                  })

                  if (actualIndex >= 0) {
                    debugLog('Emitting delete-line with actualIndex:', actualIndex)
                    autosave.cancel(line)
                    emit('delete-line', actualIndex)
                  } else {
                    // This is the auto-generated empty line - don't delete it, just clear it
                    debugLog('Auto-generated empty line - cannot delete, ignoring')
                    return
                  }
                  return
                }

                // For saved lines, ask for confirmation
                const confirmed = window.confirm('Delete this line? This action cannot be undone.')
                if (!confirmed) return
                debugLog('Emitting delete-line with line.id:', line.id)
                autosave.cancel(line)
                emit('delete-line', line.id as string)
              },
            },
            () => h(Trash2, { class: 'w-4 h-4' }),
          ),
        ])
      },
      meta: { editable: !props.readOnly },
    },
  ].filter(Boolean)
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-4 py-2">
      <button
        class="inline-flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded px-2 py-1"
        type="button"
        aria-haspopup="dialog"
        :aria-expanded="showShortcuts ? 'true' : 'false'"
        @click="showShortcuts = true"
        :title="shortcutsTitle"
      >
        <HelpCircle class="w-4 h-4" />
        <span>Shortcuts</span>
      </button>
    </div>

    <div
      class="flex-1 overflow-y-auto overflow-x-hidden"
      tabindex="0"
      @keydown="onKeydown"
      ref="containerRef"
    >
      <!-- 'as any' needed: DataTable generic TData doesn't match our CostLine columns/row types -->
      <DataTable
        class="smart-costlines-table"
        :columns="columns as any"
        :data="displayLines"
        :hide-footer="true"
        @rowClick="
          (row: any) => handleRowClick(row as CostLine, (displayLines as any).indexOf(row))
        "
      />
    </div>

    <!-- Shortcuts Help Dialog -->
    <Dialog :open="showShortcuts" @update:open="showShortcuts = $event">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
          <DialogDescription>Quick reference for grid navigation and editing</DialogDescription>
        </DialogHeader>
        <div class="text-sm space-y-2">
          <div>Enter / F2 — Start editing</div>
          <div>Enter — Commit edit</div>
          <div>Esc — Cancel edit</div>
          <div>Tab / Shift+Tab — Move between cells</div>
          <div>Arrow Up / Arrow Down — Move between rows</div>
          <div>Ctrl/Cmd+Enter — Add new line</div>
          <div>Ctrl/Cmd+D — Duplicate line</div>
          <div>Ctrl/Cmd+Backspace — Delete line</div>
          <div>Alt+Arrow Up / Alt+Arrow Down — Move line up/down</div>
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" @click="showShortcuts = false">Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Description Edit Dialog removed – all edits inline -->
  </div>
</template>

<style scoped>
/* Layout */
.smart-costlines-table :deep(table) {
  /* Let content determine widths (numeric ~8ch, totals ~12ch, desc soaks rest) */
  table-layout: auto;
  width: 100%;
}

.smart-costlines-table :deep(th),
.smart-costlines-table :deep(td) {
  word-break: break-word;
  white-space: normal;
  padding: 8px 12px;
}

.smart-costlines-table :deep(thead) {
  position: sticky;
  top: 0;
  z-index: 10;
  background: white;
}

/* Row hover */
.smart-costlines-table :deep(tbody tr:hover) {
  background-color: rgb(249, 250, 251);
}

/* Borders */
.smart-costlines-table :deep(tbody tr) {
  border: 1px solid #e5e7eb;
  border-bottom: none;
}

.smart-costlines-table :deep(tbody tr:last-child) {
  border-bottom: 1px solid #e5e7eb;
}

.smart-costlines-table :deep(td) {
  border-right: 1px solid #f3f4f6;
}

.smart-costlines-table :deep(td:last-child) {
  border-right: none;
}

/* Numeric alignment */
.smart-costlines-table :deep([data-align='right']),
.smart-costlines-table :deep(.text-right) {
  text-align: right;
}

/* Focus ring */
.smart-costlines-table :deep(input:focus),
.smart-costlines-table :deep(button:focus),
.smart-costlines-table :deep(select:focus) {
  outline: none;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.6);
}

/* === Smart width helpers (character-based) === */
.smart-costlines-table :deep(.col-8ch) {
  width: 8ch;
  max-width: 8ch;
}

.smart-costlines-table :deep(.col-10ch) {
  width: 10ch;
  max-width: 10ch;
}

.smart-costlines-table :deep(.col-12ch) {
  width: 12ch;
  max-width: 12ch;
}

/* Description column: expand to fill remaining space */
.smart-costlines-table :deep(.desc-col) {
  /* Header marker so the column can flex */
  width: auto;
  min-width: 28ch;
}

/* Source column: individual cells fit content */
.smart-costlines-table :deep(.source-col) {
  width: auto;
}

.smart-costlines-table :deep(.source-cell) {
  min-width: 12ch;
  max-width: 24ch;
}

/* Remove the old hard clamp on Description column width */
.smart-costlines-table :deep(td:has(.desc-cell)),
.smart-costlines-table :deep(th:has(.desc-cell)) {
  width: auto;
}

/* Inner Description box can cap itself visually without forcing column width */
.smart-costlines-table :deep(.desc-cell .group) {
  max-width: min(90ch, 100%);
}

/* Numeric readability */
.smart-costlines-table :deep(.numeric-input),
.smart-costlines-table :deep(.numeric-text) {
  font-variant-numeric: tabular-nums;
  font-feature-settings:
    'tnum' 1,
    'lnum' 1;
}

/* Hide spinner buttons for number inputs */
.smart-costlines-table :deep(input[type='number']) {
  -moz-appearance: textfield;
}

.smart-costlines-table :deep(input[type='number']::-webkit-outer-spin-button),
.smart-costlines-table :deep(input[type='number']::-webkit-inner-spin-button) {
  -webkit-appearance: none;
  margin: 0;
}
</style>
