<template>
  <div class="job-estimate-tab h-full flex flex-col">
    <div class="flex-shrink-0 mb-6">
      <div class="flex items-center justify-between">
        <h2 class="text-2xl font-bold text-gray-900 mb-2">
          Job Estimate
          <span v-if="isLoading" class="ml-2 text-sm text-gray-500">Loading...</span>
        </h2>
      </div>
    </div>
    <div class="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-4 min-h-0">
      <main class="bg-white rounded-xl border border-slate-200 flex flex-col min-h-0">
        <div class="px-4 py-3 border-b border-slate-200">
          <h3 class="text-lg font-semibold text-gray-900">Estimate Details</h3>
        </div>
        <div class="flex-1 overflow-hidden">
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
            <span>Loading estimate...</span>
          </div>
          <!-- BUG: @duplicate-line only works for 'material' lines. 'time'/'adjust' silently ignored.
               Need handleDuplicateLine() that respects original kind. -->
          <SmartCostLinesTable
            v-else
            :jobId="jobId"
            :tabKind="'estimate'"
            :lines="costLines"
            :readOnly="false"
            :showItemColumn="true"
            :showSourceColumn="false"
            @delete-line="handleSmartDelete"
            @add-line="handleAddEmptyLine"
            @duplicate-line="(line) => handleAddMaterial(line as any)"
            @move-line="(index, direction) => {}"
            @create-line="handleCreateFromEmpty"
          />
        </div>
      </main>
      <aside class="space-y-4 lg:sticky lg:top-16 self-start">
        <div class="bg-white rounded-xl border border-slate-200">
          <div class="p-3 w-full">
            <CompactSummaryCard
              title="Estimate Summary"
              class="w-full"
              :summary="estimateSummary"
              :costLines="costLines"
              :isLoading="isLoading"
              :revision="revision"
              @expand="showDetailedSummary = true"
            />
          </div>
        </div>
      </aside>
    </div>

    <!-- Detailed Summary Dialog -->
    <Dialog :open="showDetailedSummary" @update:open="showDetailedSummary = $event">
      <DialogContent class="sm:max-w-4xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle>Detailed Estimate Summary</DialogTitle>
          <DialogDescription>Complete breakdown of estimate costs and revenue</DialogDescription>
        </DialogHeader>
        <div class="max-h-[60vh] overflow-y-auto">
          <CostSetSummaryCard
            title="Estimate Summary"
            :summary="estimateSummary"
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
import { debugLog } from '../../utils/debug'

import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { useStockStore } from '../../stores/stockStore'
import { useCompanyDefaultsStore } from '../../stores/companyDefaults'
import SmartCostLinesTable from '../shared/SmartCostLinesTable.vue'
import CostSetSummaryCard from '../../components/shared/CostSetSummaryCard.vue'
import CompactSummaryCard from '../shared/CompactSummaryCard.vue'
import { fetchCostSet } from '../../services/costing.service'
import { useCostSummary } from '../../composables/useCostSummary'
import { useCostLinesActions } from '../../composables/useCostLinesActions'
import { schemas } from '../../api/generated/api'
import type { z } from 'zod'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../ui/dialog'
import { Button } from '../ui/button'

// Use generated API types
type CostLine = z.infer<typeof schemas.CostLine>
type CostSet = z.infer<typeof schemas.CostSet>

type Props = {
  jobId: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'cost-line-changed': []
}>()

const companyDefaultsStore = useCompanyDefaultsStore()
const companyDefaults = computed(() => companyDefaultsStore.companyDefaults)

const costLines = ref<CostLine[]>([])
const estimateCostSet = ref<CostSet | null>(null)

const isLoading = ref(false)
const revision = ref(0)
const showDetailedSummary = ref(false)

async function loadEstimate() {
  isLoading.value = true
  try {
    const costSet: CostSet = await fetchCostSet(props.jobId, 'estimate')
    estimateCostSet.value = costSet
    costLines.value = costSet.cost_lines.map((line) => ({
      ...line,
      quantity: line.quantity,
      unit_cost: line.unit_cost,
      unit_rev: line.unit_rev,
    }))
    revision.value = costSet.rev || 0
  } catch (error) {
    debugLog('Failed to load estimate cost lines:', error)
  } finally {
    isLoading.value = false
  }
}

const stockStore = useStockStore()

onMounted(async () => {
  isLoading.value = true
  try {
    // Ensure required data is present before rendering the table
    await Promise.all([
      companyDefaultsStore.isLoaded
        ? Promise.resolve()
        : companyDefaultsStore.loadCompanyDefaults(),
      stockStore.fetchStock(),
    ])
    await loadEstimate()
  } finally {
    isLoading.value = false
  }
})

const { summary: estimateSummary } = useCostSummary({
  costLines,
  includeAdjustments: true,
})

const {
  handleSmartDelete,
  handleAddEmptyLine,
  handleAddMaterial: addMaterialInternal,
  handleCreateFromEmpty: createFromEmptyInternal,
} = useCostLinesActions({
  costLines,
  jobId: props.jobId,
  costSetKind: 'estimate',
  isLoading,
  onCostLinesChanged: () => {
    emit('cost-line-changed')
  },
})

const isCompanyDefaultsReady = computed(
  () => !!companyDefaults.value && companyDefaultsStore.isLoaded,
)

async function handleAddMaterial(line: CostLine) {
  if (!isCompanyDefaultsReady.value) {
    toast.error('Company defaults not loaded yet.')
    return
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await addMaterialInternal(line as any) // BUG: needs generic handleDuplicateLine, not material-only
}

async function handleCreateFromEmpty(line: CostLine) {
  if (!isCompanyDefaultsReady.value) {
    toast.error('Company defaults not loaded yet.')
    return
  }

  await createFromEmptyInternal(line)
}
</script>

<style scoped>
:deep(.ag-theme-custom) {
  font-size: 13px;
  font-family:
    'Segoe UI',
    system-ui,
    -apple-system,
    sans-serif;
}

:deep(.ag-theme-custom .ag-header-cell) {
  font-weight: 700;
  background: #181f2a !important;
  color: #f3f4f6 !important;
  border-bottom: 1.5px solid #334155 !important;
  padding: 0 8px;
}

:deep(.ag-theme-custom .ag-cell) {
  border-right: 1px solid rgb(226, 232, 240);
  display: flex;
  align-items: center;
  padding: 0 8px;
}

:deep(.ag-theme-custom .ag-row:nth-child(odd)) {
  background-color: rgb(248, 250, 252);
}

:deep(.ag-theme-custom .ag-row:hover) {
  background-color: rgb(241, 245, 249);
}

:deep(.ag-theme-custom .ag-row-selected) {
  background-color: rgb(219, 234, 254) !important;
  border: 1px solid rgb(59, 130, 246);
}

:deep(.ag-theme-custom .ag-body-horizontal-scroll) {
  height: 14px !important;
}

:deep(.ag-theme-custom .ag-body-vertical-scroll) {
  width: 14px !important;
}

:deep(.text-center) {
  justify-content: center;
}

:deep(.ag-theme-custom .ag-selection-checkbox),
:deep(.ag-theme-custom .ag-checkbox),
:deep(.ag-theme-custom .ag-checkbox-input-wrapper),
:deep(.ag-theme-custom .ag-header-cell-menu-button),
:deep(.ag-theme-custom .ag-icon-menu),
:deep(.ag-theme-custom .ag-sort-indicator-container),
:deep(.ag-theme-custom .ag-icon),
:deep(.ag-theme-custom .ag-header-cell-filter-button),
:deep(.ag-theme-custom .ag-side-button),
:deep(.ag-theme-custom .ag-panel-title-bar-button),
:deep(.ag-theme-custom .ag-column-select-checkbox),
:deep(.ag-theme-custom .ag-group-checkbox) {
  display: none !important;
  visibility: hidden !important;
}

:deep(.ag-theme-custom .ag-header-cell-label) {
  justify-content: flex-start;
  padding-left: 0;
  width: 100%;
}

@media (max-width: 1024px) {
  :deep(.ag-theme-custom) {
    font-size: 12px;
  }

  :deep(.ag-theme-custom .ag-header-cell),
  :deep(.ag-theme-custom .ag-cell) {
    padding: 0 4px;
  }

  :deep(.ag-theme-custom .ag-header-cell[col-id='meta.labour_minutes']),
  :deep(.ag-theme-custom .ag-cell[col-id='meta.labour_minutes']) {
    display: none;
  }

  :deep(.ag-theme-custom .ag-header-cell[col-id='meta.item_cost']),
  :deep(.ag-theme-custom .ag-cell[col-id='meta.item_cost']) {
    display: none;
  }
}

@media (max-width: 640px) {
  :deep(.ag-theme-custom) {
    font-size: 11px;
  }

  :deep(.ag-theme-custom .ag-header-cell[col-id='category']),
  :deep(.ag-theme-custom .ag-cell[col-id='category']) {
    display: none;
  }

  :deep(.ag-theme-custom .ag-header-cell[col-id='actions']),
  :deep(.ag-theme-custom .ag-cell[col-id='actions']) {
    display: none;
  }
}
</style>
