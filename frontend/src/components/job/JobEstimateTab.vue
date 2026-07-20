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
            :draftSession="costLineDraftSession"
            :readOnly="false"
            :showItemColumn="true"
            :showSourceColumn="false"
            @delete-line="handleSmartDelete"
            @duplicate-line="(line) => handleAddMaterial(line as any)"
            @move-line="(index, direction) => {}"
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
import { useCostLineDrafts } from '@/composables/useCostLineDrafts'
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
    throw new Error('Company defaults not loaded yet.')
  }

  const created = await createFromEmptyInternal(line)
  if (!created) throw new Error('Cost line creation was prevented.')
  return created
}

const costLineDraftSession = useCostLineDrafts({ costLines, createLine: handleCreateFromEmpty })
</script>

<style scoped>
:deep(.text-center) {
  justify-content: center;
}
</style>
