<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="sm:max-w-4xl max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle class="text-xl font-semibold">
          Profit Breakdown - {{ monthYear }}
        </DialogTitle>
        <DialogDescription>
          Complete profit flow: Revenue - Costs = Gross Profit - Projected Expenses = Net Profit
        </DialogDescription>
        <DialogClose />
      </DialogHeader>

      <div v-if="monthlyData" class="py-4 space-y-6">
        <!-- Profit Flow Summary -->
        <div class="bg-gray-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4">Profit Flow</h3>
          <div class="space-y-3">
            <div class="flex justify-between items-center">
              <span class="text-gray-700">Total Revenue</span>
              <span class="font-semibold text-lg">{{
                formatCurrency(totalRevenue, { decimals: 0 })
              }}</span>
            </div>
            <div class="flex justify-between items-center text-sm text-gray-600">
              <span class="ml-4">- Total Costs</span>
              <span>{{ formatCurrency(totalCosts, { decimals: 0 }) }}</span>
            </div>
            <hr class="border-gray-300" />
            <div class="flex justify-between items-center">
              <span class="text-gray-700 font-medium">= Gross Profit</span>
              <span class="font-semibold text-lg text-green-600">{{
                formatCurrency(monthlyData.gross_profit, { decimals: 0 })
              }}</span>
            </div>
            <div class="flex justify-between items-center text-sm text-gray-600">
              <span class="ml-4">- Projected Expenses</span>
              <span>{{ formatCurrency(projectedExpenses, { decimals: 0 }) }}</span>
            </div>
            <hr class="border-gray-300" />
            <div class="flex justify-between items-center">
              <span class="text-gray-900 font-semibold">= Net Profit</span>
              <span class="font-bold text-xl" :class="netProfitClass">{{
                formatCurrency(monthlyData.net_profit, { decimals: 0 })
              }}</span>
            </div>
          </div>
        </div>

        <!-- Revenue Breakdown -->
        <div class="bg-blue-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-blue-900">Revenue Breakdown</h3>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="text-center">
              <div class="text-2xl font-bold text-blue-700">
                {{ formatCurrency(laborRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-blue-600">Labor Revenue</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-blue-700">
                {{ formatCurrency(materialRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-blue-600">Material Revenue</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-blue-700">
                {{ formatCurrency(adjustmentRevenue, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-blue-600">Adjustments</div>
            </div>
          </div>
        </div>

        <!-- Cost Breakdown -->
        <div class="bg-red-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-red-900">Cost Breakdown</h3>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="text-center">
              <div class="text-2xl font-bold text-red-700">
                {{ formatCurrency(laborCosts, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-red-600">Labor Costs</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-red-700">
                {{ formatCurrency(materialCosts, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-red-600">Material Costs</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-red-700">
                {{ formatCurrency(adjustmentCosts, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-red-600">Adjustment Costs</div>
            </div>
          </div>
        </div>

        <!-- Performance Metrics -->
        <div class="bg-green-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-green-900">Performance Metrics</h3>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="text-center">
              <div class="text-2xl font-bold text-green-700">{{ grossProfitMargin }}%</div>
              <div class="text-sm text-green-600">Gross Profit Margin</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-green-700">{{ netProfitMargin }}%</div>
              <div class="text-sm text-green-600">Net Profit Margin</div>
            </div>
            <div class="text-center">
              <div class="text-2xl font-bold text-green-700">
                {{ formatCurrency(dailyTarget, { decimals: 0 }) }}
              </div>
              <div class="text-sm text-green-600">Daily GP Target</div>
            </div>
          </div>
        </div>

        <!-- Target Comparison -->
        <div class="bg-yellow-50 p-6 rounded-lg">
          <h3 class="font-semibold text-lg mb-4 text-yellow-900">Target Analysis</h3>
          <div class="space-y-3">
            <div class="flex justify-between items-center">
              <span class="text-gray-700">Daily GP Target</span>
              <span class="font-medium">{{ formatCurrency(dailyTarget, { decimals: 0 }) }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-gray-700">Working Days</span>
              <span class="font-medium">{{ monthlyData.working_days }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-gray-700">Monthly GP Target</span>
              <span class="font-medium">{{ formatCurrency(monthlyTarget, { decimals: 0 }) }}</span>
            </div>
            <hr class="border-yellow-300" />
            <div class="flex justify-between items-center">
              <span class="text-gray-900 font-semibold">Target Performance</span>
              <span class="font-bold text-lg" :class="targetPerformanceClass"
                >{{ targetPerformance }}%</span
              >
            </div>
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
type Thresholds = z.infer<typeof schemas.KPIThresholds>
type DayKPI = z.infer<typeof schemas.KPIDayData>

const props = defineProps<{
  monthlyData: MonthlyTotals | null
  thresholds: Thresholds | null
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

const totalRevenue = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.total_revenue || 0)
  }, 0)
})

const totalCosts = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.total_cost || 0)
  }, 0)
})

const laborRevenue = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.time_revenue || 0)
  }, 0)
})

const materialRevenue = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.material_revenue || 0)
  }, 0)
})

const adjustmentRevenue = computed(() => {
  return totalRevenue.value - laborRevenue.value - materialRevenue.value
})

const laborCosts = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.staff_cost || 0)
  }, 0)
})

const materialCosts = computed(() => {
  if (!props.calendarData) return 0
  return Object.values(props.calendarData).reduce((sum, day) => {
    return sum + (day?.details?.material_cost || 0)
  }, 0)
})

const adjustmentCosts = computed(() => {
  return totalCosts.value - laborCosts.value - materialCosts.value
})

const projectedExpenses = computed(() => {
  if (!props.monthlyData || !props.thresholds) return 0
  return props.thresholds.kpi_daily_gp_green * props.monthlyData.working_days
})

const dailyTarget = computed(() => {
  return props.thresholds?.kpi_daily_gp_green || 0
})

const monthlyTarget = computed(() => {
  if (!props.monthlyData || !props.thresholds) return 0
  return props.thresholds.kpi_daily_gp_green * props.monthlyData.working_days
})

const grossProfitMargin = computed(() => {
  if (!totalRevenue.value || !props.monthlyData) return 0
  return Math.round((props.monthlyData.gross_profit / totalRevenue.value) * 100)
})

const netProfitMargin = computed(() => {
  if (!totalRevenue.value || !props.monthlyData) return 0
  return Math.round((props.monthlyData.net_profit / totalRevenue.value) * 100)
})

const targetPerformance = computed(() => {
  if (!props.monthlyData || !monthlyTarget.value) return 0
  return Math.round((props.monthlyData.gross_profit / monthlyTarget.value) * 100)
})

const netProfitClass = computed(() => {
  if (!props.monthlyData) return ''
  return props.monthlyData.net_profit >= 0 ? 'text-green-600' : 'text-red-600'
})

const targetPerformanceClass = computed(() => {
  const perf = targetPerformance.value
  if (perf >= 100) return 'text-green-600'
  if (perf >= 80) return 'text-yellow-600'
  return 'text-red-600'
})
</script>
