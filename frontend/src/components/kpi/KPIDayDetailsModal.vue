<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="sm:max-w-4xl max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle class="text-xl font-semibold">
          {{ formatDateTitle(dayData?.date) }}
          <span v-if="dayData?.holiday" class="text-sm font-normal text-gray-500 ml-2"
            >(Holiday)</span
          >
        </DialogTitle>
        <DialogDescription>
          <span v-if="dayData?.holiday"> Holiday wage costs and staff breakdown </span>
          <span v-else> Daily revenue, cost, and profit breakdown with job-by-job analysis </span>
        </DialogDescription>
        <DialogClose />
      </DialogHeader>

      <div v-if="dayData" class="grid grid-cols-1 md:grid-cols-2 gap-6 py-4">
        <!-- Revenue Section -->
        <div class="bg-gray-50 p-4 rounded-lg">
          <h3 class="font-semibold text-lg mb-4">Revenue</h3>
          <div class="space-y-2">
            <div class="flex justify-between items-center text-xs">
              <span class="text-gray-700">Labour Revenue</span>
              <span class="font-medium">{{
                formatCurrency(dayData.details.time_revenue, { decimals: 0 })
              }}</span>
            </div>
            <div class="flex justify-between items-center text-xs">
              <span class="text-gray-700">Material Revenue</span>
              <span class="font-medium">{{
                formatCurrency(dayData.details.material_revenue, { decimals: 0 })
              }}</span>
            </div>
            <div class="flex justify-between items-center text-xs">
              <span class="text-gray-700">Adjustment Revenue</span>
              <span class="font-medium">{{
                formatCurrency(adjustmentRevenue, { decimals: 0 })
              }}</span>
            </div>
            <hr class="border-gray-300" />
            <div class="flex justify-between items-center font-bold text-xs">
              <span>Total Revenue</span>
              <span>{{ formatCurrency(dayData.details.total_revenue, { decimals: 0 }) }}</span>
            </div>
          </div>
        </div>

        <!-- Cost Section -->
        <div class="bg-gray-50 p-4 rounded-lg">
          <h3 class="font-semibold text-lg mb-4">Cost</h3>
          <div class="space-y-2">
            <div class="flex justify-between items-center text-xs">
              <span class="text-gray-700">Labor Cost</span>
              <span class="font-medium">{{
                formatCurrency(dayData.details.staff_cost, { decimals: 0 })
              }}</span>
            </div>
            <div class="flex justify-between items-center text-xs">
              <span class="text-gray-700">Material Cost</span>
              <span class="font-medium">{{
                formatCurrency(dayData.details.material_cost, { decimals: 0 })
              }}</span>
            </div>
            <div class="flex justify-between items-center text-xs">
              <span class="text-gray-700">Adjustment Cost</span>
              <span class="font-medium">{{ formatCurrency(adjustmentCost, { decimals: 0 }) }}</span>
            </div>
            <hr class="border-gray-300" />
            <div class="flex justify-between items-center font-bold text-xs">
              <span>Total Cost</span>
              <span>{{ formatCurrency(dayData.details.total_cost, { decimals: 0 }) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Gross Profit Breakdown -->
      <div v-if="dayData" class="bg-gray-50 p-4 rounded-lg mb-6">
        <h3 class="font-semibold text-lg mb-4">Gross Profit Breakdown</h3>
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div class="flex justify-between items-center text-xs">
            <span class="text-gray-700">Labor Profit</span>
            <span class="font-medium">{{ formatCurrency(laborProfit, { decimals: 0 }) }}</span>
          </div>
          <div class="flex justify-between items-center text-xs">
            <span class="text-gray-700">Material Profit</span>
            <span class="font-medium">{{ formatCurrency(materialProfit, { decimals: 0 }) }}</span>
          </div>
          <div class="flex justify-between items-center text-xs">
            <span class="text-gray-700">Adjustment Profit</span>
            <span class="font-medium">{{ formatCurrency(adjustmentProfit, { decimals: 0 }) }}</span>
          </div>
          <div class="flex justify-between items-center font-bold text-xs">
            <span>Total Gross Profit</span>
            <span>{{ formatCurrency(dayData.gross_profit, { decimals: 0 }) }}</span>
          </div>
        </div>
      </div>

      <!-- Profit by Job Section -->
      <div
        v-if="dayData && dayData.details.job_breakdown.length > 0"
        class="bg-gray-50 p-4 rounded-lg"
      >
        <h3 class="font-semibold text-lg mb-4">Profit by Job</h3>
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead>
              <tr class="border-b border-gray-300">
                <th class="text-left py-2 px-3 font-medium text-blue-600">Job #</th>
                <th class="text-right py-2 px-3 font-medium text-blue-600">Labour</th>
                <th class="text-right py-2 px-3 font-medium text-blue-600">Materials</th>
                <th class="text-right py-2 px-3 font-medium text-blue-600">Adjustments</th>
                <th class="text-right py-2 px-3 font-medium text-blue-600">Total</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="job in dayData.details.job_breakdown"
                :key="job.job_number"
                class="border-b border-gray-200 hover:bg-gray-100 text-xs"
              >
                <td class="py-1.5 px-2">
                  <button
                    @click="handleJobClick(job.job_id)"
                    :title="`${job.job_name} — ${job.client_name}`"
                    class="text-blue-600 hover:text-blue-800 hover:underline cursor-pointer"
                  >
                    {{ job.job_number }}
                  </button>
                </td>
                <td class="py-1.5 px-2 text-right">
                  {{ formatCurrency(job.labour_profit, { decimals: 0 }) }}
                </td>
                <td class="py-1.5 px-2 text-right">
                  {{ formatCurrency(job.material_profit, { decimals: 0 }) }}
                </td>
                <td class="py-1.5 px-2 text-right">
                  {{ formatCurrency(job.adjustment_profit, { decimals: 0 }) }}
                </td>
                <td class="py-1.5 px-2 text-right font-medium">
                  {{ formatCurrency(job.profit, { decimals: 0 }) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-else-if="isLoading" class="bg-gray-50 p-4 rounded-lg text-center">
        <div class="flex items-center justify-center gap-2">
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
          <p class="text-gray-500">Loading day details, please wait</p>
        </div>
      </div>

      <div v-else-if="dayData" class="bg-gray-50 p-4 rounded-lg text-center">
        <p class="text-gray-500">No job data available for this day</p>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from '@/components/ui/dialog'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import { formatCurrency } from '@/utils/string-formatting'

// Use generated API types
type KPIDayData = z.infer<typeof schemas.KPIDayData>

type Props = {
  dayData: KPIDayData | null
  isOpen: boolean
  isLoading?: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:isOpen': [value: boolean]
  jobClick: [jobId: string]
}>()

const isOpen = computed({
  get: () => props.isOpen,
  set: (value: boolean) => emit('update:isOpen', value),
})

const adjustmentRevenue = computed(() => {
  if (!props.dayData) return 0
  return (
    props.dayData.details.total_revenue -
    props.dayData.details.time_revenue -
    props.dayData.details.material_revenue
  )
})

const adjustmentCost = computed(() => {
  if (!props.dayData) return 0
  return (
    props.dayData.details.total_cost -
    props.dayData.details.staff_cost -
    props.dayData.details.material_cost
  )
})

const laborProfit = computed(() => {
  if (!props.dayData) return 0
  return props.dayData.details.time_revenue - props.dayData.details.staff_cost
})

const materialProfit = computed(() => {
  if (!props.dayData) return 0
  return props.dayData.details.material_revenue - props.dayData.details.material_cost
})

const adjustmentProfit = computed(() => {
  if (!props.dayData) return 0
  return adjustmentRevenue.value - adjustmentCost.value
})

function formatDateTitle(dateString: string | undefined): string {
  if (!dateString) return ''

  const date = new Date(dateString)
  return date.toLocaleDateString('en-NZ', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

function handleJobClick(jobId: string) {
  emit('jobClick', jobId)
}
</script>
