<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="sm:max-w-4xl max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle class="text-xl font-semibold">
          Labour Breakdown - {{ monthYear }}
        </DialogTitle>
        <DialogDescription> Complete labour hours, costs, and revenue analysis </DialogDescription>
        <DialogClose />
      </DialogHeader>

      <div v-if="monthlyData && calendarData" class="py-4 space-y-6">
        <!-- Labour Overview -->
        <div class="bg-blue-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-blue-900">Labour Overview</h3>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="text-center">
              <div class="text-3xl font-bold text-blue-700">
                {{ formatHours(monthlyData.total_hours) }}
              </div>
              <div class="text-sm text-blue-600">Total Labour Hours</div>
              <div class="text-xs text-gray-500 mt-1">All recorded time</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-blue-700">
                {{ formatHours(monthlyData.billable_hours) }}
              </div>
              <div class="text-sm text-blue-600">Billable Hours</div>
              <div class="text-xs text-gray-500 mt-1">Client chargeable time</div>
            </div>
            <div class="text-center">
              <div class="text-3xl font-bold text-blue-700">{{ formatHours(totalShopHours) }}</div>
              <div class="text-sm text-blue-600">Shop Hours</div>
              <div class="text-xs text-gray-500 mt-1">Workshop/production time</div>
            </div>
          </div>
        </div>

        <!-- Labour Financial Breakdown -->
        <div class="bg-green-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-green-900">Labour Financial Breakdown</h3>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <!-- Costs -->
            <div>
              <h4 class="font-medium mb-3 text-green-800">Labour Costs</h4>
              <div class="space-y-2">
                <div class="flex justify-between items-center">
                  <span class="text-gray-700">Total Labour Cost</span>
                  <span class="font-semibold text-lg">{{
                    formatCurrency(totalLabourCost, { decimals: 0 })
                  }}</span>
                </div>
                <div class="flex justify-between items-center text-sm text-gray-600">
                  <span class="ml-4">Shop Labour Cost</span>
                  <span>{{ formatCurrency(shopLabourCost, { decimals: 0 }) }}</span>
                </div>
                <div class="flex justify-between items-center text-sm text-gray-600">
                  <span class="ml-4">Other Labour Cost</span>
                  <span>{{ formatCurrency(otherLabourCost, { decimals: 0 }) }}</span>
                </div>
              </div>
            </div>

            <!-- Revenue -->
            <div>
              <h4 class="font-medium mb-3 text-green-800">Labour Revenue</h4>
              <div class="space-y-2">
                <div class="flex justify-between items-center">
                  <span class="text-gray-700">Total Labour Revenue</span>
                  <span class="font-semibold text-lg">{{
                    formatCurrency(totalLabourRevenue, { decimals: 0 })
                  }}</span>
                </div>
                <div class="flex justify-between items-center text-sm text-gray-600">
                  <span class="ml-4">Average Rate</span>
                  <span>{{ formatCurrency(averageLabourRate, { decimals: 0 }) }}/hr</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Labour Efficiency Metrics -->
        <div class="bg-yellow-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-yellow-900">Labour Efficiency</h3>
          <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div class="text-center">
              <div class="text-2xl font-bold text-yellow-700">{{ utilizationRate }}%</div>
              <div class="text-sm text-yellow-600">Utilization Rate</div>
              <div class="text-xs text-gray-500">Billable / Total Hours</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-yellow-700">{{ shopUtilizationRate }}%</div>
              <div class="text-sm text-yellow-600">Shop Utilization</div>
              <div class="text-xs text-gray-500">Shop / Total Hours</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-yellow-700">
                {{ formatCurrency(labourProfitMargin, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-yellow-600">Labour Profit</div>
              <div class="text-xs text-gray-500">Revenue - Cost</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-yellow-700">{{ labourProfitPercent }}%</div>
              <div class="text-sm text-yellow-600">Profit Margin</div>
              <div class="text-xs text-gray-500">Profit / Revenue</div>
            </div>
          </div>
        </div>

        <!-- Daily Labour Breakdown -->
        <div class="bg-gray-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-gray-900">Daily Labour Summary</h3>
          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-gray-300">
                  <th class="text-left py-2 px-3 font-medium text-gray-600">Date</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Total Hours</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Billable Hours</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Shop Hours</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Labour Cost</th>
                  <th class="text-right py-2 px-3 font-medium text-gray-600">Labour Revenue</th>
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
                  <td class="py-2 px-3 text-right">{{ formatHours(day.total_hours) }}</td>
                  <td class="py-2 px-3 text-right">{{ formatHours(day.billable_hours) }}</td>
                  <td class="py-2 px-3 text-right">{{ formatHours(day.shop_hours) }}</td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(day.details?.staff_cost || 0, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(day.details?.time_revenue || 0, { decimals: 0 }) }}
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="border-t-2 border-gray-400 font-semibold bg-gray-100">
                  <td class="py-2 px-3">TOTAL</td>
                  <td class="py-2 px-3 text-right">{{ formatHours(monthlyData.total_hours) }}</td>
                  <td class="py-2 px-3 text-right">
                    {{ formatHours(monthlyData.billable_hours) }}
                  </td>
                  <td class="py-2 px-3 text-right">{{ formatHours(totalShopHours) }}</td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(totalLabourCost, { decimals: 0 }) }}
                  </td>
                  <td class="py-2 px-3 text-right">
                    {{ formatCurrency(totalLabourRevenue, { decimals: 0 }) }}
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

type MonthlyTotals = z.infer<typeof schemas.KPIMonthlyTotals>
type DayKPI = z.infer<typeof schemas.KPIDayData>

const props = defineProps<{
  monthlyData: MonthlyTotals | null
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

const totalShopHours = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.shop_hours || 0)
  }, 0)
})

const totalLabourCost = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.staff_cost || 0)
  }, 0)
})

const totalLabourRevenue = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.time_revenue || 0)
  }, 0)
})

const shopLabourCost = computed(() => {
  if (!props.monthlyData || props.monthlyData.total_hours === 0) return 0
  const shopHourRatio = totalShopHours.value / props.monthlyData.total_hours
  return totalLabourCost.value * shopHourRatio
})

const otherLabourCost = computed(() => {
  return totalLabourCost.value - shopLabourCost.value
})

const averageLabourRate = computed(() => {
  if (!props.monthlyData || props.monthlyData.billable_hours === 0) return 0
  return totalLabourRevenue.value / props.monthlyData.billable_hours
})

const utilizationRate = computed(() => {
  if (!props.monthlyData || props.monthlyData.total_hours === 0) return 0
  return Math.round((props.monthlyData.billable_hours / props.monthlyData.total_hours) * 100)
})

const shopUtilizationRate = computed(() => {
  if (!props.monthlyData || props.monthlyData.total_hours === 0) return 0
  return Math.round((totalShopHours.value / props.monthlyData.total_hours) * 100)
})

const labourProfitMargin = computed(() => {
  return totalLabourRevenue.value - totalLabourCost.value
})

const labourProfitPercent = computed(() => {
  if (totalLabourRevenue.value === 0) return 0
  return Math.round((labourProfitMargin.value / totalLabourRevenue.value) * 100)
})

function formatHours(hours: number): string {
  return kpiService.formatHours(hours)
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
