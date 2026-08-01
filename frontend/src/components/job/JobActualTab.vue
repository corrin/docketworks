<template>
  <div class="job-actual-tab h-full grid grid-rows-[auto_1fr] gap-4">
    <!-- HEADER -->
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-2xl font-bold text-gray-900">
          Actual Costs
          <span v-if="isLoading" class="ml-2 text-sm text-gray-500">Loading...</span>
        </h2>
        <p class="text-sm text-gray-500">
          View and add actual costs from stock consumption and adjustments
        </p>
      </div>

      <!-- KPIs as chips -->
      <ul class="hidden xl:flex items-center gap-2 shrink-0">
        <li class="h-10 px-3 rounded-lg border border-slate-200 bg-white flex items-center gap-2">
          <span class="w-1.5 h-6 rounded-full bg-blue-500"></span>
          <span class="text-[11px] uppercase tracking-wide text-slate-600">Estimate</span>
          <strong class="tabular-nums text-slate-900">{{ formatCurrency(estimateTotal) }}</strong>
        </li>
        <li
          v-if="pricingMethodology === 'fixed_price'"
          class="h-10 px-3 rounded-lg border border-slate-200 bg-white flex items-center gap-2"
        >
          <span class="w-1.5 h-6 rounded-full bg-purple-500"></span>
          <span class="text-[11px] uppercase tracking-wide text-slate-600">Quote</span>
          <strong class="tabular-nums text-slate-900">{{ formatCurrency(quoteTotal) }}</strong>
        </li>
        <li
          data-automation-id="JobActualTab-time-expenses"
          class="h-10 px-3 rounded-lg border border-slate-200 bg-white flex items-center gap-2"
        >
          <span class="w-1.5 h-6 rounded-full bg-emerald-500"></span>
          <span class="text-[11px] uppercase tracking-wide text-slate-600">Time & Expenses</span>
          <strong class="tabular-nums text-slate-900">{{ formatCurrency(timeAndExpenses) }}</strong>
        </li>
      </ul>
    </div>

    <!-- CONTENT: STICKY GRID ASIDE + MAIN -->
    <div class="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-4 min-h-0">
      <!-- MAIN (GRID) -->
      <main class="bg-white rounded-xl border border-slate-200 flex flex-col min-h-0">
        <div class="px-4 py-3 border-b border-slate-200">
          <h3 class="text-lg font-semibold text-gray-900">Actual Details</h3>
        </div>

        <div class="flex-1 min-h-0 overflow-auto">
          <div v-if="isLoading" class="h-full flex items-center justify-center text-gray-500 gap-2">
            <svg class="animate-spin h-5 w-5" viewBox="0 0 24 24">
              <circle
                class="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                stroke-width="4"
              />
              <path
                class="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <span>Loading cost lines...</span>
          </div>

          <div v-else>
            <SmartCostLinesTable
              :jobId="jobId"
              :tabKind="'actual'"
              :lines="costLines"
              :draftSession="costLineDraftSession"
              :readOnly="false"
              :showItemColumn="true"
              :showSourceColumn="true"
              :sourceResolver="resolveSource"
              :allowedKinds="['material', 'adjust']"
              :blockedFieldsByKind="blockedFieldsByKind"
              :consumeStockFn="consumeStockForNewLine"
              :allowTypeEdit="true"
              :negativeStockIds="negativeStockIds"
              @delete-line="handleSmartDelete"
              @duplicate-line="() => {}"
              @move-line="() => {}"
            />
          </div>
        </div>
      </main>

      <!-- ASIDE (STICKY): Actual summary -->
      <aside class="space-y-4 lg:sticky lg:top-16 self-start">
        <div class="bg-white rounded-xl border border-slate-200">
          <div class="p-3 w-full">
            <CompactSummaryCard
              title="Actual Summary"
              class="w-full"
              :summary="actualSummary"
              :costLines="costLines"
              :isLoading="isLoading"
              :revision="revision"
              @expand="showDetailedSummary = true"
            />
          </div>
        </div>
      </aside>
    </div>

    <!-- DIALOGS -->
    <Dialog :open="showDetailedSummary" @update:open="showDetailedSummary = $event">
      <DialogContent class="sm:max-w-4xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle>Detailed Actual Summary</DialogTitle>
          <DialogDescription>Complete breakdown of actual costs and revenue</DialogDescription>
        </DialogHeader>
        <div class="max-h-[60vh] overflow-y-auto">
          <CostSetSummaryCard
            title="Actual Summary"
            :summary="actualSummary"
            :costLines="costLines"
            :isLoading="isLoading"
            :revision="revision"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showDetailedSummary = false">Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import debug from 'debug'

const log = debug('job:actual')
import { toLocalDateString } from '../../utils/dateUtils'
import { formatCurrency } from '@/utils/string-formatting'
import { normalizeOptionalDecimal } from '@/utils/number'
import { onMounted, ref, computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import CostSetSummaryCard from '../shared/CostSetSummaryCard.vue'
import CompactSummaryCard from '../shared/CompactSummaryCard.vue'
import { fetchCostSet } from '../../services/costing.service'
import { costlineService } from '../../services/costline.service'
import { schemas } from '../../api/generated/api'
import { useSmartCostLineDelete } from '../../composables/useSmartCostLineDelete'
import { useCostSummary } from '../../composables/useCostSummary'
import { useCostLineDrafts } from '@/composables/useCostLineDrafts'
import { api } from '../../api/client'
import { z } from 'zod'
import type { KindOption } from '../shared/SmartCostLinesTable.vue'
import { useStockStore } from '../../stores/stockStore'
import SmartCostLinesTable from '../shared/SmartCostLinesTable.vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../ui/dialog'
import { Button } from '../ui/button'
import { useSaveFeedback } from '@/composables/useSaveFeedback'

type CostLine = z.infer<typeof schemas.CostLine>
type CostSet = z.infer<typeof schemas.CostSet>
type KanbanStaff = z.infer<typeof schemas.KanbanStaff>
type StockConsumeRequest = z.infer<typeof schemas.StockConsumeRequest>

// Type guard functions to safely access meta and ext_refs
function isDeliveryReceiptMeta(meta: unknown): meta is { source: string; po_number?: string } {
  return (
    typeof meta === 'object' &&
    meta !== null &&
    'source' in meta &&
    typeof (meta as Record<string, unknown>).source === 'string' &&
    (meta as Record<string, unknown>).source === 'delivery_receipt'
  )
}

function isTimesheetMeta(meta: unknown): meta is { staff_id: string; date?: string } {
  return (
    typeof meta === 'object' &&
    meta !== null &&
    'staff_id' in meta &&
    typeof (meta as Record<string, unknown>).staff_id === 'string'
  )
}

function isDeliveryReceiptExtRefs(extRefs: unknown): extRefs is { purchase_order_id: string } {
  return (
    typeof extRefs === 'object' &&
    extRefs !== null &&
    'purchase_order_id' in extRefs &&
    typeof (extRefs as Record<string, unknown>).purchase_order_id === 'string'
  )
}

function isStockExtRefs(extRefs: unknown): extRefs is { stock_id: string } {
  return (
    typeof extRefs === 'object' &&
    extRefs !== null &&
    'stock_id' in extRefs &&
    typeof (extRefs as Record<string, unknown>).stock_id === 'string'
  )
}

const props = defineProps<{
  jobId: string
  pricingMethodology: string
}>()
const jobActualSaveFeedback = useSaveFeedback(`job-actual:${props.jobId}`, {
  toastErrors: false,
})

const emit = defineEmits<{
  'cost-line-changed': []
}>()

const stockStore = useStockStore()

// KPI chips. Invoice figures deliberately live in Finish Job only, so there is
// one authoritative place showing what the customer owes.
const estimateTotal = ref(0)
const quoteTotal = ref(0)
const costsSummaryLoading = ref(false)
const timeAndExpenses = computed(() => actualSummary.value.rev)

const router = useRouter()

const costLines = ref<CostLine[]>([])
const staffMap = ref<Record<string, KanbanStaff>>({})
const isLoading = ref(false)
const revision = ref(0)
const showDetailedSummary = ref(false)

// For actual tab specifics
const blockedFieldsByKind = ref<Record<KindOption, string[]>>({
  material: ['quantity', 'unit_cost', 'unit_rev'], // Allow desc editing for material items
  adjust: [],
  time: [],
})

const negativeStockSet = reactive(new Set<string>())
const negativeStockIds = computed(() => [...negativeStockSet].sort())

async function checkAndUpdateNegativeStocks() {
  negativeStockSet.clear()

  // Simple call - store handles dedup
  await stockStore.fetchStock()

  // Use stock store data instead of calling API directly
  for (const stock of stockStore.items) {
    if (stock.quantity < 0) {
      negativeStockSet.add(stock.id)
    }
  }
}

async function loadStaff() {
  try {
    // Include inactive staff since this job may have historical time entries
    const staff: KanbanStaff[] = await api.accounts_staff_all_list({
      queries: { include_inactive: 'true' },
    })
    staffMap.value = staff.reduce(
      (acc: Record<string, KanbanStaff>, s: KanbanStaff) => {
        acc[s.id] = s
        return acc
      },
      {} as Record<string, KanbanStaff>,
    )
  } catch (error) {
    log('Failed to load staff data:', error)
  }
}

async function loadActualCosts() {
  isLoading.value = true
  try {
    const costSet: CostSet = await fetchCostSet(props.jobId, 'actual')

    costLines.value = costSet.cost_lines

    revision.value = costSet.rev || 0

    // Ensure stock is loaded so UI has stock library available
    await checkAndUpdateNegativeStocks()
  } catch (error) {
    log('Failed to load actual cost lines:', error)
  } finally {
    isLoading.value = false
  }
}

async function loadCostsSummary() {
  costsSummaryLoading.value = true
  try {
    const response = await api.job_jobs_costs_summary_retrieve({
      params: { job_id: props.jobId },
    })
    estimateTotal.value = response.estimate?.rev || 0
    quoteTotal.value = response.quote?.rev || 0
  } catch (error) {
    log('Failed to load costs summary:', error)
  } finally {
    costsSummaryLoading.value = false
  }
}

// Use the smart delete composable
const { handleSmartDelete } = useSmartCostLineDelete({
  costLines,
  onCostLineChanged: async () => {
    emit('cost-line-changed')
    await checkAndUpdateNegativeStocks() // Re-check after delete (backend auto-reverts)
  },
  isLoading,
})

// Function for consumption on new material line selection
async function consumeStockForNewLine(payload: {
  line: CostLine
  stockId: string
  quantity: number
  unitCost: number
  unitRev: number
}) {
  if (!props.jobId) return

  try {
    jobActualSaveFeedback.saving()

    const normalizedUnitCost = normalizeOptionalDecimal(payload.unitCost, {
      decimalPlaces: 2,
    })
    const normalizedUnitRev = normalizeOptionalDecimal(payload.unitRev, {
      decimalPlaces: 2,
    })

    const request: StockConsumeRequest = {
      job_id: props.jobId,
      quantity: payload.quantity,
      ...(normalizedUnitCost !== undefined ? { unit_cost: normalizedUnitCost } : {}),
      ...(normalizedUnitRev !== undefined ? { unit_rev: normalizedUnitRev } : {}),
    }

    const response = await api.consumeStock(request, {
      params: { id: payload.stockId },
    })

    // Replace the temp line with the created one
    const tempLineIndex = costLines.value.findIndex((l) => l === payload.line)

    if (tempLineIndex >= 0) {
      // Common case: there was a temp line in the parent component
      costLines.value[tempLineIndex] = response.line
    } else {
      // Initial case: user was on the local emptyLine of the table (child)
      // Insert the created line in the parent's array
      costLines.value.push(response.line)
    }

    log('[CONSUME-STOCK] New array: ', costLines.value, ' Received line: ', response.line)

    jobActualSaveFeedback.saved()
    emit('cost-line-changed')

    // Refresh stock data and check if resulted in negative
    await stockStore.fetchStock()
    const stock = stockStore.items.find((s) => s.id === payload.stockId)
    if (stock && stock.quantity < 0) {
      toast.warning(`Warning: Stock now negative (${Math.abs(stock.quantity).toFixed(3)} units).`)
    }

    checkAndUpdateNegativeStocks()
  } catch (error) {
    jobActualSaveFeedback.error('Failed to consume stock.')
    toast.error('Failed to consume stock.')
    console.error('Failed to consume stock:', error)
    throw error // To prevent unblocking in table
  }
}

// Adjustment persistence callback; material creation remains in consumeStockForNewLine.
async function handleCreateLine(line: CostLine): Promise<CostLine> {
  if (line.kind !== 'adjust') {
    throw new Error(`Cannot persist ${line.kind} through the adjustment creation path.`)
  }

  jobActualSaveFeedback.saving()
  try {
    const createPayload = {
      kind: 'adjust' as const,
      desc: line.desc,
      quantity: line.quantity,
      unit_cost: line.unit_cost,
      unit_rev: line.unit_rev,
      accounting_date: toLocalDateString(),
      ext_refs: (line.ext_refs as Record<string, unknown>) || {},
      meta: { source: 'manual_adjustment' },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }

    const created = await costlineService.createCostLine(props.jobId, 'actual', createPayload)
    jobActualSaveFeedback.saved()
    emit('cost-line-changed')
    return created
  } catch (error) {
    jobActualSaveFeedback.error('Failed to create adjustment.')
    toast.error('Failed to create adjustment.')
    console.error('Failed to create adjustment:', error)
    throw error
  }
}

const costLineDraftSession = useCostLineDrafts({ costLines, createLine: handleCreateLine })

onMounted(async () => {
  await Promise.all([loadStaff(), loadActualCosts(), loadCostsSummary()])
})

// Use the cost summary composable (simple version for actual)
const { simpleSummary: actualSummary } = useCostSummary({
  costLines,
})

function navigateToDeliveryReceipt(purchaseOrderId: string) {
  log('Received po id: ', purchaseOrderId)
  router.push({
    name: '/purchasing/po/[id]',
    params: { id: purchaseOrderId },
  })
}

function navigateToTimesheet(staffId: string, date?: string) {
  if (date) {
    router.push({
      name: '/timesheets/entry',
      query: { staffId, date },
    })
  } else {
    router.push({
      name: '/timesheets/entry',
      query: { staffId },
    })
  }
}

// TODO: add better navigation flow with front-end path parameter to prepopulate the search bar with the stock name
function navigateToStock(/*stockId: string*/) {
  router.push({
    name: '/purchasing/stock',
    // params: { stockId },
  })
}

// Resolver for Source column used by SmartCostLinesTable
function resolveSource(
  line: CostLine,
): { visible: boolean; label: string; onClick?: () => void } | null {
  // Material from Delivery Receipt
  if (
    String(line.kind) === 'material' &&
    isDeliveryReceiptMeta(line.meta) &&
    isDeliveryReceiptExtRefs(line.ext_refs)
  ) {
    const label = line.meta.po_number || 'Delivery Receipt'
    const deliveryExtRefs = line.ext_refs
    return {
      visible: true,
      label,
      onClick: () => navigateToDeliveryReceipt(deliveryExtRefs.purchase_order_id),
    }
  }

  // Material from Stock
  if (String(line.kind) === 'material' && isStockExtRefs(line.ext_refs)) {
    return {
      visible: true,
      label: 'Stock',
      onClick: () => navigateToStock(/* extRefs.stock_id */),
    }
  }

  // Time from Timesheet
  if (String(line.kind) === 'time' && isTimesheetMeta(line.meta)) {
    const meta = line.meta
    const staffName = staffMap.value[meta.staff_id]?.display_name || 'Timesheet'
    const date = meta.date
    return {
      visible: true,
      label: staffName,
      onClick: () => navigateToTimesheet(meta.staff_id, date),
    }
  }

  // Adjustment entry
  if (String(line.kind) === 'adjust') {
    return { visible: true, label: 'Adjustment' }
  }

  // No source info
  return null
}
</script>
