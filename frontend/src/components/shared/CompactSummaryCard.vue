<template>
  <div class="compact-summary-card bg-white rounded-lg border border-gray-200 p-4 shadow-sm">
    <div class="flex items-center justify-between mb-3">
      <h4 class="text-sm font-semibold text-gray-900">{{ title }}</h4>
      <Button
        variant="outline"
        size="sm"
        @click="$emit('expand')"
        aria-label="View Details"
        class="h-7 w-7 p-0"
      >
        <Maximize2 class="w-3 h-3" />
      </Button>
    </div>

    <div v-if="isLoading" class="flex items-center justify-center py-4">
      <svg class="animate-spin h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24">
        <circle
          class="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
    </div>

    <div v-else-if="typedSummary" class="space-y-3">
      <!-- Total Cost -->
      <div class="flex justify-between items-center">
        <span class="text-xs text-gray-500">Total Cost</span>
        <span class="text-lg font-bold text-red-600">{{ formatCurrency(typedSummary.cost) }}</span>
      </div>

      <!-- Total Revenue -->
      <div class="flex justify-between items-center">
        <span class="text-xs text-gray-500">Total Revenue</span>
        <span class="text-lg font-bold text-green-600">{{ formatCurrency(typedSummary.rev) }}</span>
      </div>

      <!-- Profit -->
      <div class="flex justify-between items-center pt-2 border-t border-gray-200">
        <span class="text-xs text-gray-500">Profit</span>
        <span :class="['text-lg font-bold', profit >= 0 ? 'text-green-600' : 'text-red-600']">
          {{ formatCurrency(profit) }}
        </span>
      </div>

      <!-- Total Hours -->
      <div class="flex justify-between items-center">
        <span class="text-xs text-gray-500">Total Hours</span>
        <span class="text-sm font-semibold text-blue-600">{{
          formatHoursDisplay(typedSummary.hours)
        }}</span>
      </div>
    </div>

    <div v-else class="flex flex-col items-center justify-center py-4">
      <FileX class="w-8 h-8 text-gray-300 mb-2" />
      <p class="text-gray-500 text-xs">No data available</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { FileX, Maximize2 } from 'lucide-vue-next'
import { Button } from '../ui/button'
import { schemas } from '../../api/generated/api'
import { formatCurrency, formatHoursDisplay } from '@/utils/string-formatting'
import { z } from 'zod'

type CostLine = z.infer<typeof schemas.CostLine>
type CostSet = z.infer<typeof schemas.CostSet>

const props = defineProps<{
  title?: string
  summary?: CostSet['summary'] | null
  costLines?: CostLine[]
  isLoading?: boolean
  revision?: number
}>()

defineEmits<{
  expand: []
}>()

const summaryFromCostLines = computed(() => {
  if (!props.costLines) {
    return null
  }

  let cost = 0
  let rev = 0
  let hours = 0

  for (const line of props.costLines) {
    const quantity = Number(line.quantity) || 0
    const unitCost = Number(line.unit_cost) || 0
    const unitRev = Number(line.unit_rev) || 0

    cost += quantity * unitCost
    rev += quantity * unitRev

    if (line.kind === 'time') {
      hours += quantity
    }
  }

  return {
    cost,
    rev,
    hours,
  }
})

const typedSummary = computed(() => {
  if (summaryFromCostLines.value) {
    return summaryFromCostLines.value
  }

  if (!props.summary || typeof props.summary !== 'object') {
    return null
  }

  const summary = props.summary as Record<string, unknown>

  if (
    typeof summary.cost === 'number' &&
    typeof summary.rev === 'number' &&
    typeof summary.hours === 'number'
  ) {
    return summary as {
      cost: number
      rev: number
      hours: number
      created?: string
    }
  }

  return null
})

const profit = computed(() => {
  if (!typedSummary.value) return 0
  return typedSummary.value.rev - typedSummary.value.cost
})
</script>

<style scoped>
.compact-summary-card {
  min-width: 200px;
  max-width: 325px;
}
</style>
