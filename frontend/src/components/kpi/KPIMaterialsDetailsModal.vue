<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="sm:max-w-4xl max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle class="text-xl font-semibold">
          Materials & Adjustments Breakdown - {{ monthYear }}
        </DialogTitle>
        <DialogDescription>
          Complete materials, adjustments, and markup analysis
        </DialogDescription>
        <DialogClose />
      </DialogHeader>

      <div v-if="calendarData" class="py-4 space-y-6">
        <!-- Materials & Adjustments Overview -->
        <div class="bg-purple-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-purple-900">Revenue Overview</h3>
          <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div class="text-center">
              <div class="text-3xl font-bold text-purple-700">
                {{ formatCurrency(materialRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-purple-600">Material Revenue</div>
              <div class="text-xs text-gray-500 mt-1">Material sales</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-purple-700">
                {{ formatCurrency(adjustmentRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-purple-600">Adjustment Revenue</div>
              <div class="text-xs text-gray-500 mt-1">Price adjustments</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-purple-700">
                {{ formatCurrency(totalNonLabourRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-purple-600">Total Non-Labour</div>
              <div class="text-xs text-gray-500 mt-1">Materials + Adjustments</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-purple-700">{{ nonLabourPercentage }}%</div>
              <div class="text-sm text-purple-600">Of Total Revenue</div>
              <div class="text-xs text-gray-500 mt-1">Non-labour portion</div>
            </div>
          </div>
        </div>

        <!-- Cost Breakdown -->
        <div class="bg-red-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-red-900">Cost Breakdown</h3>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="text-center">
              <div class="text-3xl font-bold text-red-700">
                {{ formatCurrency(materialCosts, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-red-600">Material Costs</div>
              <div class="text-xs text-gray-500 mt-1">Cost of materials</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-red-700">
                {{ formatCurrency(adjustmentCosts, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-red-600">Adjustment Costs</div>
              <div class="text-xs text-gray-500 mt-1">Cost adjustments</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-red-700">
                {{ formatCurrency(totalNonLabourCosts, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-red-600">Total Non-Labour Costs</div>
              <div class="text-xs text-gray-500 mt-1">Materials + Adjustments</div>
            </div>
          </div>
        </div>

        <!-- Profit & Margin Analysis -->
        <div class="bg-green-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-green-900">Profit & Margin Analysis</h3>
          <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div class="text-center">
              <div class="text-3xl font-bold text-green-700">
                {{ formatCurrency(materialProfit, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-green-600">Material Profit</div>
              <div class="text-xs text-gray-500 mt-1">Revenue - Cost</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-green-700">{{ materialMargin }}%</div>
              <div class="text-sm text-green-600">Material Margin</div>
              <div class="text-xs text-gray-500 mt-1">Profit / Revenue</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-green-700">
                {{ formatCurrency(adjustmentProfit, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-green-600">Adjustment Profit</div>
              <div class="text-xs text-gray-500 mt-1">Revenue - Cost</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-green-700">
                {{ formatCurrency(totalNonLabourProfit, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-green-600">Total Non-Labour Profit</div>
              <div class="text-xs text-gray-500 mt-1">Combined profit</div>
            </div>
          </div>
        </div>

        <!-- Revenue vs Labour Comparison -->
        <div class="bg-blue-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-blue-900">Revenue Mix Analysis</h3>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="text-center">
              <div class="text-3xl font-bold text-blue-700">
                {{ formatCurrency(labourRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-blue-600">Labour Revenue</div>
              <div class="text-xs text-gray-500 mt-1">{{ labourPercentage }}% of total</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-blue-700">
                {{ formatCurrency(totalNonLabourRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-blue-600">Non-Labour Revenue</div>
              <div class="text-xs text-gray-500 mt-1">{{ nonLabourPercentage }}% of total</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-blue-700">
                {{ formatCurrency(totalRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-blue-600">Total Revenue</div>
              <div class="text-xs text-gray-500 mt-1">100% of revenue</div>
            </div>
          </div>
        </div>

        <!-- Daily Materials & Adjustments Breakdown -->
        <div class="bg-gray-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-gray-900">Daily Breakdown</h3>
          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-gray-300">
                  <th class="text-left py-2 px-3 font-medium text-gray-600">Date</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Material Revenue</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Material Cost</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Material Profit</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Adjustment Revenue</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Adjustment Cost</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Total Non-Labour</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="day in sortedDays"
                  :key="day.date"
                  class="border-b border-gray-200 hover:bg-gray-100 text-sm"
                  :class="{ 'bg-gray-100': day.holiday }"
                >
                  <td class="py-2 px-3">
                    {{ formatDateShort(day.date) }}
                    <span v-if="day.holiday" class="text-xs text-gray-500 ml-1">(Holiday)</span>
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(day.details?.material_revenue || 0, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(day.details?.material_cost || 0, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{
                      formatCurrency(
                        (day.details?.material_revenue || 0) - (day.details?.material_cost || 0),
                        { decimals: 0 },
                      )
                    }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(getDayAdjustmentRevenue(day), { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(getDayAdjustmentCost(day), { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right font-medium">
                    {{ formatCurrency(getDayTotalNonLabour(day), { decimals: 0 }) }}
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="border-t-2 border-gray-400 font-semibold bg-gray-100">
                  <td class="py-2 px-3">TOTAL</td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(materialRevenue, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(materialCosts, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(materialProfit, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(adjustmentRevenue, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(adjustmentCosts, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(totalNonLabourRevenue, { decimals: 0 }) }}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
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
import { z } from 'zod'
import { kpiService } from '@/services/kpi.service'
import { formatCurrency } from '@/utils/string-formatting'

type DayKPI = z.infer<typeof schemas.KPIDayData>

const props = defineProps<{
  calendarData: Record<string, DayKPI> | null
  year: number
  month: number
  isOpen: boolean
}>()

const emit = defineEmits<{
  'update:isOpen': [value: boolean]
}>()

const isOpen = computed({
  get: () => props.isOpen,
  set: (value: boolean) => emit('update:isOpen', value),
})

const monthYear = computed(() => {
  if (!props.year || !props.month) return ''
  return `${kpiService.getMonthName(props.month)} ${props.year}`
})

const sortedDays = computed(() => {
  if (!props.calendarData) return []
  return Object.values(props.calendarData).sort((a, b) => {
    return new Date(a.date).getTime() - new Date(b.date).getTime()
  })
})

const materialRevenue = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.material_revenue || 0)
  }, 0)
})

const labourRevenue = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.time_revenue || 0)
  }, 0)
})

const totalRevenue = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.total_revenue || 0)
  }, 0)
})

const adjustmentRevenue = computed(() => {
  return totalRevenue.value - labourRevenue.value - materialRevenue.value
})

const totalNonLabourRevenue = computed(() => {
  return materialRevenue.value + adjustmentRevenue.value
})

const materialCosts = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.material_cost || 0)
  }, 0)
})

const totalCosts = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.total_cost || 0)
  }, 0)
})

const labourCosts = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.staff_cost || 0)
  }, 0)
})

const adjustmentCosts = computed(() => {
  return totalCosts.value - labourCosts.value - materialCosts.value
})

const totalNonLabourCosts = computed(() => {
  return materialCosts.value + adjustmentCosts.value
})

const materialProfit = computed(() => {
  return materialRevenue.value - materialCosts.value
})

const adjustmentProfit = computed(() => {
  return adjustmentRevenue.value - adjustmentCosts.value
})

const totalNonLabourProfit = computed(() => {
  return materialProfit.value + adjustmentProfit.value
})

const materialMargin = computed(() => {
  if (materialRevenue.value === 0) return 0
  return Math.round((materialProfit.value / materialRevenue.value) * 100)
})

const labourPercentage = computed(() => {
  if (totalRevenue.value === 0) return 0
  return Math.round((labourRevenue.value / totalRevenue.value) * 100)
})

const nonLabourPercentage = computed(() => {
  if (totalRevenue.value === 0) return 0
  return Math.round((totalNonLabourRevenue.value / totalRevenue.value) * 100)
})

function getDayAdjustmentRevenue(day: DayKPI): number {
  const totalRev = day.details?.total_revenue || 0
  const labourRev = day.details?.time_revenue || 0
  const materialRev = day.details?.material_revenue || 0
  return totalRev - labourRev - materialRev
}

function getDayAdjustmentCost(day: DayKPI): number {
  const totalCost = day.details?.total_cost || 0
  const labourCost = day.details?.staff_cost || 0
  const materialCost = day.details?.material_cost || 0
  return totalCost - labourCost - materialCost
}

function getDayTotalNonLabour(day: DayKPI): number {
  const materialRev = day.details?.material_revenue || 0
  const adjustmentRev = getDayAdjustmentRevenue(day)
  return materialRev + adjustmentRev
}

function formatDateShort(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleDateString('en-NZ', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}
</script>
