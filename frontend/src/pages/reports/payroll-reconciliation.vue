<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <Scale class="w-8 h-8 text-indigo-400" />
              Payroll Reconciliation
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportToCsv"
                :disabled="loading || !data"
                class="text-sm px-4 py-2"
              >
                <Download class="w-4 h-4 mr-2" />
                Export CSV
              </Button>
              <Button
                variant="default"
                @click="refreshData"
                :disabled="loading"
                class="text-sm px-4 py-2"
              >
                <RefreshCw class="w-4 h-4 mr-2" :class="{ 'animate-spin': loading }" />
                Refresh
              </Button>
            </div>
          </div>

          <!-- Date Range Filters -->
          <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
            <div class="flex flex-wrap items-center gap-4">
              <div class="flex items-center gap-2">
                <label for="start-date" class="text-sm font-medium text-gray-700">
                  Start Date:
                </label>
                <input
                  id="start-date"
                  v-model="dateRange.startDate"
                  type="date"
                  class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="loadData"
                />
              </div>
              <div class="flex items-center gap-2">
                <label for="end-date" class="text-sm font-medium text-gray-700"> End Date: </label>
                <input
                  id="end-date"
                  v-model="dateRange.endDate"
                  type="date"
                  class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="loadData"
                />
              </div>
              <div class="flex gap-2">
                <Button variant="outline" size="sm" @click="setDateRange('thisFinancialYear')">
                  This FY
                </Button>
                <Button variant="outline" size="sm" @click="setDateRange('lastFinancialYear')">
                  Last FY
                </Button>
                <Button variant="outline" size="sm" @click="setDateRange('last30Weeks')">
                  Last 30 Weeks
                </Button>
              </div>
            </div>
          </div>

          <!-- Summary Cards -->
          <div v-if="data" class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Xero Total</p>
                  <p
                    class="text-2xl font-bold text-gray-900"
                    data-automation-id="PayrollReconciliation-xero-total"
                  >
                    {{ formatCurrency(data.grand_totals.xero_gross) }}
                  </p>
                </div>
                <DollarSign class="h-8 w-8 text-blue-500" />
              </div>
            </div>

            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">JM Total</p>
                  <p
                    class="text-2xl font-bold text-gray-900"
                    data-automation-id="PayrollReconciliation-jm-total"
                  >
                    {{ formatCurrency(data.grand_totals.jm_cost) }}
                  </p>
                </div>
                <DollarSign class="h-8 w-8 text-green-500" />
              </div>
            </div>

            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Difference</p>
                  <p
                    class="text-2xl font-bold"
                    :class="data.grand_totals.diff < 0 ? 'text-red-600' : 'text-green-600'"
                    data-automation-id="PayrollReconciliation-diff-value"
                  >
                    {{ formatCurrency(data.grand_totals.diff) }}
                    <span class="text-sm font-normal">
                      ({{ data.grand_totals.diff_pct.toFixed(1) }}%)
                    </span>
                  </p>
                </div>
                <DollarSign
                  class="h-8 w-8"
                  :class="data.grand_totals.diff < 0 ? 'text-red-500' : 'text-green-500'"
                />
              </div>
            </div>
          </div>

          <!-- Loading State -->
          <div v-if="loading" class="flex items-center justify-center py-12">
            <RefreshCw class="h-8 w-8 animate-spin text-indigo-500" />
            <span class="ml-2 text-lg text-gray-600">Loading payroll reconciliation data...</span>
          </div>

          <!-- Error State -->
          <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="flex items-center">
              <AlertCircle class="h-5 w-5 text-red-400 mr-2" />
              <span class="text-red-800">{{ error }}</span>
            </div>
          </div>

          <!-- Heatmap Grid -->
          <div
            v-if="data && !loading && !error"
            class="bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden"
            data-automation-id="PayrollReconciliation-heatmap"
          >
            <TooltipProvider :delay-duration="200">
              <div class="overflow-x-auto">
                <table class="min-w-full">
                  <thead class="bg-gray-50">
                    <tr>
                      <th
                        class="sticky left-0 z-10 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border-r border-gray-200"
                      >
                        Week
                      </th>
                      <th
                        v-for="name in data.heatmap.staff_names"
                        :key="name"
                        class="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                      >
                        {{ name }}
                      </th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-gray-100">
                    <tr v-for="row in data.heatmap.rows" :key="row.week_start">
                      <td
                        class="sticky left-0 z-10 bg-white px-3 py-2 text-sm font-medium text-gray-700 whitespace-nowrap border-r border-gray-200"
                      >
                        {{ row.week_start }}
                      </td>
                      <td
                        v-for="name in data.heatmap.staff_names"
                        :key="name"
                        class="px-3 py-2 text-center text-xs font-medium whitespace-nowrap"
                        :class="heatmapCellClass(row.cells[name] ?? null)"
                      >
                        <Tooltip>
                          <TooltipTrigger as-child>
                            <span class="block w-full cursor-default">
                              {{ formatCellValue(row.cells[name] ?? null) }}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent
                            v-if="getStaffWeekDetail(row.week_start, name)"
                            class="max-w-xs"
                          >
                            <div class="text-xs space-y-1">
                              <p class="font-semibold">{{ name }} — {{ row.week_start }}</p>
                              <div class="grid grid-cols-2 gap-x-3">
                                <span class="text-gray-400">Xero:</span>
                                <span>
                                  {{ getStaffWeekDetail(row.week_start, name)!.xero_hours }}h /
                                  {{
                                    formatCurrency(
                                      getStaffWeekDetail(row.week_start, name)!.xero_gross,
                                    )
                                  }}
                                </span>
                                <span class="text-gray-400">JM:</span>
                                <span>
                                  {{ getStaffWeekDetail(row.week_start, name)!.jm_hours }}h /
                                  {{
                                    formatCurrency(
                                      getStaffWeekDetail(row.week_start, name)!.jm_cost,
                                    )
                                  }}
                                </span>
                                <span class="text-gray-400">Gap:</span>
                                <span>
                                  {{
                                    formatCurrency(
                                      getStaffWeekDetail(row.week_start, name)!.cost_diff,
                                    )
                                  }}
                                </span>
                                <span class="text-gray-400 pl-2">Hours:</span>
                                <span>
                                  {{
                                    formatCurrency(
                                      getStaffWeekDetail(row.week_start, name)!.hours_cost_impact,
                                    )
                                  }}
                                </span>
                                <span class="text-gray-400 pl-2">Rate:</span>
                                <span>
                                  {{
                                    formatCurrency(
                                      getStaffWeekDetail(row.week_start, name)!.rate_cost_impact,
                                    )
                                  }}
                                </span>
                              </div>
                            </div>
                          </TooltipContent>
                        </Tooltip>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </TooltipProvider>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { Scale, Download, RefreshCw, AlertCircle, DollarSign } from 'lucide-vue-next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useFinancialYear } from '@/composables/useFinancialYear'
import {
  fetchPayrollReconciliation,
  fetchAlignedDateRange,
  exportPayrollReconciliationCsv,
  type PayrollReconciliationResponse,
} from '@/services/payroll-reconciliation-report.service'
import { formatCurrency } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'
import { toast } from 'vue-sonner'

const { getDateRange } = useFinancialYear()

const loading = ref(false)
const error = ref<string | null>(null)
const data = ref<PayrollReconciliationResponse | null>(null)

const dateRange = ref({
  startDate: '',
  endDate: '',
})

function setDateRange(preset: 'thisFinancialYear' | 'lastFinancialYear' | 'last30Weeks') {
  if (preset === 'last30Weeks') {
    const end = new Date()
    const start = new Date()
    start.setDate(start.getDate() - 30 * 7)
    dateRange.value = {
      startDate: toLocalDateString(start),
      endDate: toLocalDateString(end),
    }
  } else {
    const range = getDateRange(preset)
    dateRange.value = { startDate: range.startDate, endDate: range.endDate }
  }
  loadData()
}

async function loadData() {
  if (!dateRange.value.startDate || !dateRange.value.endDate) return
  loading.value = true
  error.value = null
  try {
    const aligned = await fetchAlignedDateRange(dateRange.value.startDate, dateRange.value.endDate)
    dateRange.value.startDate = aligned.aligned_start
    dateRange.value.endDate = aligned.aligned_end

    data.value = await fetchPayrollReconciliation(
      dateRange.value.startDate,
      dateRange.value.endDate,
    )
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Failed to load report'
    error.value = msg
    toast.error(msg)
  } finally {
    loading.value = false
  }
}

function refreshData() {
  loadData()
}

function exportToCsv() {
  if (data.value) exportPayrollReconciliationCsv(data.value)
}

function heatmapCellClass(value: number | null): string {
  if (value === null) return 'bg-gray-100 text-gray-400'
  const abs = Math.abs(value)
  if (abs < 1) return 'bg-green-100 text-green-800'
  if (value < 0) {
    if (abs < 50) return 'bg-red-100 text-red-700'
    if (abs < 200) return 'bg-red-200 text-red-800'
    if (abs < 500) return 'bg-red-300 text-red-900'
    return 'bg-red-400 text-red-950'
  }
  if (abs < 50) return 'bg-blue-100 text-blue-700'
  if (abs < 200) return 'bg-blue-200 text-blue-800'
  if (abs < 500) return 'bg-blue-300 text-blue-900'
  return 'bg-blue-400 text-blue-950'
}

function formatCellValue(value: number | null): string {
  if (value === null) return ''
  if (Math.abs(value) < 1) return '$0'
  return formatCurrency(value)
}

function getStaffWeekDetail(weekStart: string, staffName: string) {
  if (!data.value) return null
  const week = data.value.weeks.find((w) => w.week_start === weekStart)
  if (!week) return null
  return week.staff.find((s) => s.name === staffName) ?? null
}

onMounted(() => {
  setDateRange('thisFinancialYear')
})
</script>
