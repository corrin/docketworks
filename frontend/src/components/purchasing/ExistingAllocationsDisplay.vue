<template>
  <div class="space-y-4">
    <!-- Previous Allocations Section -->
    <div v-if="hasExistingAllocations" class="bg-blue-50 border border-blue-200 rounded-lg p-4">
      <h3 class="font-semibold text-blue-900 mb-3 flex items-center gap-2">
        <History class="w-5 h-5" />
        Previous Allocations
      </h3>

      <div class="space-y-3">
        <div
          v-for="(lineAllocations, lineId) in existingAllocations"
          :key="lineId"
          class="bg-white rounded-lg p-3 border border-blue-100"
        >
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm font-medium text-gray-700">
              {{ getLineDescription(lineId) }}
            </span>
            <span class="text-xs text-gray-500">
              {{ getTotalAllocated(lineAllocations) }} units allocated
            </span>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div
              v-for="(allocation, index) in lineAllocations"
              :key="index"
              class="p-2 border rounded-lg bg-gray-50 text-sm"
            >
              <div class="flex items-center justify-between">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-1 mb-1">
                    <Package
                      v-if="allocation.type === 'job'"
                      class="w-3 h-3 text-blue-500 flex-shrink-0"
                    />
                    <MapPin v-else class="w-3 h-3 text-gray-500 flex-shrink-0" />
                    <span class="font-medium text-xs truncate">
                      {{ allocation.job_name }}
                    </span>
                  </div>
                  <div class="text-xs text-gray-600">
                    Qty: {{ allocation.quantity }}
                    <span
                      v-if="
                        allocation.type === 'job' &&
                        allocation.retail_rate &&
                        allocation.retail_rate > 0
                      "
                    >
                      | {{ allocation.retail_rate }}%
                    </span>
                    <span v-if="allocation.stock_location">
                      | {{ allocation.stock_location }}
                    </span>
                  </div>
                  <div v-if="allocation.allocation_date" class="text-xs text-gray-500 mt-1">
                    {{ formatDate(allocation.allocation_date) }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- No Previous Allocations Message -->
    <div v-else class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
      <Package class="w-8 h-8 text-gray-400 mx-auto mb-2" />
      <p class="text-gray-600 text-sm">No previous allocations for this purchase order</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Package, MapPin, History } from 'lucide-vue-next'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

type PurchaseOrderLine = z.infer<typeof schemas.PurchaseOrderLine>
type AllocationItem = z.infer<typeof schemas.AllocationItem>

const props = defineProps<{
  existingAllocations: Record<string, AllocationItem[]>
  lines: PurchaseOrderLine[]
}>()

const hasExistingAllocations = computed(() => {
  const hasKeys = Object.keys(props.existingAllocations).length > 0
  const hasData = Object.values(props.existingAllocations).some(
    (allocations) => allocations && allocations.length > 0,
  )

  return hasKeys && hasData
})

const getLineDescription = (lineId: string): string => {
  let line = props.lines.find((l) => l.id === lineId)
  if (!line) {
    line = props.lines.find((l) => l.id === String(lineId) || String(l.id) === lineId)
  }

  return line ? line.description : `Unknown Line (ID: ${lineId})`
}

const getTotalAllocated = (allocations: AllocationItem[]): number => {
  return allocations.reduce((sum, alloc) => sum + alloc.quantity, 0)
}

const formatDate = (dateString: string): string => {
  const date = new Date(dateString)
  return date.toLocaleDateString('en-NZ', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>
