<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <FileText class="w-8 h-8 text-indigo-400" />
              Profit & Loss Report (Xero)
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportToCsv"
                :disabled="loading || !reportData"
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

          <!-- Date Range and Period Filters -->
          <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
            <!-- Primary Date Range -->
            <div class="flex flex-wrap items-center gap-4 mb-4">
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
            </div>

            <!-- Period Presets -->
            <div class="flex flex-wrap gap-2 mb-4">
              <Button
                variant="outline"
                size="sm"
                @click="setDateRange('thisMonth')"
                :class="{ 'bg-indigo-50 border-indigo-300': selectedPreset === 'thisMonth' }"
              >
                This Month
              </Button>
              <Button
                variant="outline"
                size="sm"
                @click="setDateRange('lastMonth')"
                :class="{ 'bg-indigo-50 border-indigo-300': selectedPreset === 'lastMonth' }"
              >
                Last Month
              </Button>
              <Button
                variant="outline"
                size="sm"
                @click="setDateRange('thisQuarter')"
                :class="{ 'bg-indigo-50 border-indigo-300': selectedPreset === 'thisQuarter' }"
              >
                This Quarter
              </Button>
              <Button
                variant="outline"
                size="sm"
                @click="setDateRange('lastQuarter')"
                :class="{ 'bg-indigo-50 border-indigo-300': selectedPreset === 'lastQuarter' }"
              >
                Last Quarter
              </Button>
              <Button
                variant="outline"
                size="sm"
                @click="setDateRange('thisFinancialYear')"
                :class="{
                  'bg-indigo-50 border-indigo-300': selectedPreset === 'thisFinancialYear',
                }"
              >
                This Financial Year
              </Button>
              <Button
                variant="outline"
                size="sm"
                @click="setDateRange('lastFinancialYear')"
                :class="{
                  'bg-indigo-50 border-indigo-300': selectedPreset === 'lastFinancialYear',
                }"
              >
                Last Financial Year
              </Button>
              <Button
                variant="outline"
                size="sm"
                @click="setDateRange('monthToDate')"
                :class="{ 'bg-indigo-50 border-indigo-300': selectedPreset === 'monthToDate' }"
              >
                Month to Date
              </Button>
              <Button
                variant="outline"
                size="sm"
                @click="setDateRange('yearToDate')"
                :class="{ 'bg-indigo-50 border-indigo-300': selectedPreset === 'yearToDate' }"
              >
                Year to Date
              </Button>
            </div>

            <!-- Comparison Settings -->
            <div class="border-t border-gray-200 pt-4 mt-4">
              <div class="flex flex-wrap items-center gap-4">
                <div class="flex items-center gap-2">
                  <label for="compare-periods" class="text-sm font-medium text-gray-700">
                    Compare:
                  </label>
                  <input
                    id="compare-periods"
                    v-model.number="comparison.periods"
                    type="number"
                    min="0"
                    max="12"
                    class="w-20 rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                    @change="loadData"
                  />
                  <span class="text-sm text-gray-600">period(s)</span>
                </div>

                <div class="flex items-center gap-2">
                  <label for="period-length" class="text-sm font-medium text-gray-700">
                    Period Length:
                  </label>
                  <select
                    id="period-length"
                    v-model="comparison.periodLength"
                    class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                    @change="loadData"
                  >
                    <option value="month">Month</option>
                    <option value="quarter">Quarter</option>
                    <option value="year">Year</option>
                  </select>
                </div>

                <Button
                  v-if="comparison.periods > 0"
                  variant="ghost"
                  size="sm"
                  @click="clearComparison"
                >
                  <X class="w-4 h-4 mr-1" />
                  Clear Comparison
                </Button>
              </div>
            </div>
          </div>

          <!-- Error State -->
          <div
            v-if="error"
            class="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3"
          >
            <AlertCircle class="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div class="text-sm text-red-800">
              <p class="font-medium">Error Loading Data</p>
              <p>{{ error }}</p>
            </div>
          </div>

          <!-- Summary Cards -->
          <div v-if="reportData && summary" class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Total Revenue</p>
                  <p class="text-2xl font-bold text-green-600">
                    {{ formatCurrency(summary.totalRevenue) }}
                  </p>
                </div>
                <TrendingUp class="h-8 w-8 text-green-500" />
              </div>
            </div>

            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Gross Profit</p>
                  <p
                    class="text-2xl font-bold"
                    :class="summary.grossProfit >= 0 ? 'text-green-600' : 'text-red-600'"
                  >
                    {{ formatCurrency(summary.grossProfit) }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Margin: {{ formatPercentage(summary.grossProfitMargin) }}
                  </p>
                </div>
                <BarChart3 class="h-8 w-8 text-blue-500" />
              </div>
            </div>

            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Net Profit</p>
                  <p
                    class="text-2xl font-bold"
                    :class="summary.netProfit >= 0 ? 'text-green-600' : 'text-red-600'"
                  >
                    {{ formatCurrency(summary.netProfit) }}
                  </p>
                  <p class="text-xs text-gray-500">
                    Margin: {{ formatPercentage(summary.netProfitMargin) }}
                  </p>
                </div>
                <DollarSign
                  class="h-8 w-8"
                  :class="summary.netProfit >= 0 ? 'text-green-500' : 'text-red-500'"
                />
              </div>
            </div>
          </div>

          <!-- P&L Report Table -->
          <div v-if="!loading && reportData" class="flex-1 overflow-hidden flex flex-col">
            <div
              class="bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden flex-1 flex flex-col"
            >
              <div class="overflow-x-auto flex-1">
                <table class="min-w-full divide-y divide-gray-200">
                  <thead class="bg-gray-50 sticky top-0">
                    <tr>
                      <th
                        scope="col"
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Account
                      </th>
                      <th
                        scope="col"
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        {{ formatDateRangeHeader(reportData.start_date, reportData.end_date) }}
                      </th>
                      <th
                        v-for="(label, index) in reportData.compare_period_labels"
                        :key="index"
                        scope="col"
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        {{ label }}
                      </th>
                    </tr>
                  </thead>
                  <tbody class="bg-white divide-y divide-gray-200">
                    <!-- Revenue Section -->
                    <tr class="bg-indigo-50">
                      <td
                        colspan="100"
                        class="px-6 py-3 text-sm font-bold text-indigo-900 uppercase"
                      >
                        Revenue
                      </td>
                    </tr>
                    <tr
                      v-for="item in reportData.revenue.line_items"
                      :key="item.account_code"
                      class="hover:bg-gray-50"
                    >
                      <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-900">
                        <span class="text-gray-500 text-xs mr-2">{{ item.account_code }}</span>
                        {{ item.account_name }}
                      </td>
                      <td class="px-6 py-2 whitespace-nowrap text-sm text-right text-gray-900">
                        {{ formatCurrency(item.amount) }}
                      </td>
                      <td
                        v-for="(amt, index) in item.compare_amounts"
                        :key="index"
                        class="px-6 py-2 whitespace-nowrap text-sm text-right text-gray-600"
                      >
                        {{ formatCurrency(amt) }}
                      </td>
                    </tr>
                    <tr class="bg-gray-100 font-semibold">
                      <td class="px-6 py-3 text-sm text-gray-900">Total Revenue</td>
                      <td class="px-6 py-3 text-sm text-right text-gray-900">
                        {{ formatCurrency(reportData.revenue.total) }}
                      </td>
                      <td
                        v-for="(total, index) in reportData.revenue.compare_totals"
                        :key="index"
                        class="px-6 py-3 text-sm text-right text-gray-700"
                      >
                        {{ formatCurrency(total) }}
                      </td>
                    </tr>

                    <!-- Cost of Sales Section -->
                    <tr class="bg-red-50">
                      <td colspan="100" class="px-6 py-3 text-sm font-bold text-red-900 uppercase">
                        Cost of Sales
                      </td>
                    </tr>
                    <tr
                      v-for="item in reportData.cost_of_sales.line_items"
                      :key="item.account_code"
                      class="hover:bg-gray-50"
                    >
                      <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-900">
                        <span class="text-gray-500 text-xs mr-2">{{ item.account_code }}</span>
                        {{ item.account_name }}
                      </td>
                      <td class="px-6 py-2 whitespace-nowrap text-sm text-right text-gray-900">
                        {{ formatCurrency(item.amount) }}
                      </td>
                      <td
                        v-for="(amt, index) in item.compare_amounts"
                        :key="index"
                        class="px-6 py-2 whitespace-nowrap text-sm text-right text-gray-600"
                      >
                        {{ formatCurrency(amt) }}
                      </td>
                    </tr>
                    <tr class="bg-gray-100 font-semibold">
                      <td class="px-6 py-3 text-sm text-gray-900">Total Cost of Sales</td>
                      <td class="px-6 py-3 text-sm text-right text-gray-900">
                        {{ formatCurrency(reportData.cost_of_sales.total) }}
                      </td>
                      <td
                        v-for="(total, index) in reportData.cost_of_sales.compare_totals"
                        :key="index"
                        class="px-6 py-3 text-sm text-right text-gray-700"
                      >
                        {{ formatCurrency(total) }}
                      </td>
                    </tr>

                    <!-- Gross Profit -->
                    <tr class="bg-blue-100 font-bold">
                      <td class="px-6 py-3 text-sm text-blue-900 uppercase">Gross Profit</td>
                      <td
                        class="px-6 py-3 text-sm text-right"
                        :class="
                          reportData.gross_profit.amount >= 0 ? 'text-green-700' : 'text-red-700'
                        "
                      >
                        {{ formatCurrency(reportData.gross_profit.amount) }}
                      </td>
                      <td
                        v-for="(amt, index) in reportData.gross_profit.compare_amounts"
                        :key="index"
                        class="px-6 py-3 text-sm text-right"
                        :class="amt >= 0 ? 'text-green-700' : 'text-red-700'"
                      >
                        {{ formatCurrency(amt) }}
                      </td>
                    </tr>

                    <!-- Operating Expenses Section -->
                    <tr class="bg-orange-50">
                      <td
                        colspan="100"
                        class="px-6 py-3 text-sm font-bold text-orange-900 uppercase"
                      >
                        Operating Expenses
                      </td>
                    </tr>
                    <tr
                      v-for="item in reportData.operating_expenses.line_items"
                      :key="item.account_code"
                      class="hover:bg-gray-50"
                    >
                      <td class="px-6 py-2 whitespace-nowrap text-sm text-gray-900">
                        <span class="text-gray-500 text-xs mr-2">{{ item.account_code }}</span>
                        {{ item.account_name }}
                      </td>
                      <td class="px-6 py-2 whitespace-nowrap text-sm text-right text-gray-900">
                        {{ formatCurrency(item.amount) }}
                      </td>
                      <td
                        v-for="(amt, index) in item.compare_amounts"
                        :key="index"
                        class="px-6 py-2 whitespace-nowrap text-sm text-right text-gray-600"
                      >
                        {{ formatCurrency(amt) }}
                      </td>
                    </tr>
                    <tr class="bg-gray-100 font-semibold">
                      <td class="px-6 py-3 text-sm text-gray-900">Total Operating Expenses</td>
                      <td class="px-6 py-3 text-sm text-right text-gray-900">
                        {{ formatCurrency(reportData.operating_expenses.total) }}
                      </td>
                      <td
                        v-for="(total, index) in reportData.operating_expenses.compare_totals"
                        :key="index"
                        class="px-6 py-3 text-sm text-right text-gray-700"
                      >
                        {{ formatCurrency(total) }}
                      </td>
                    </tr>

                    <!-- Net Profit -->
                    <tr class="bg-indigo-100 font-bold text-lg">
                      <td class="px-6 py-4 text-sm text-indigo-900 uppercase">Net Profit</td>
                      <td
                        class="px-6 py-4 text-sm text-right"
                        :class="
                          reportData.net_profit.amount >= 0 ? 'text-green-700' : 'text-red-700'
                        "
                      >
                        {{ formatCurrency(reportData.net_profit.amount) }}
                      </td>
                      <td
                        v-for="(amt, index) in reportData.net_profit.compare_amounts"
                        :key="index"
                        class="px-6 py-4 text-sm text-right"
                        :class="amt >= 0 ? 'text-green-700' : 'text-red-700'"
                      >
                        {{ formatCurrency(amt) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- Footer - Validation Information -->
              <div class="border-t border-gray-200 bg-blue-50 px-6 py-4">
                <div class="flex items-start gap-3">
                  <Info class="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                  <div class="text-sm text-blue-800">
                    <p class="font-medium mb-1">Data Source: Xero Accounting</p>
                    <p class="text-xs text-blue-700">
                      This report is generated directly from Xero data to validate that our system's
                      financial data matches Xero's records. Compare this report with the same
                      period in Xero to ensure data consistency.
                    </p>
                    <p class="text-xs text-blue-600 mt-2">
                      <strong>Report Period:</strong>
                      {{ formatDateRangeHeader(reportData.start_date, reportData.end_date) }}
                      <span v-if="reportData.compare_periods && reportData.compare_periods > 0">
                        | <strong>Comparing:</strong> {{ reportData.compare_periods }}
                        {{ reportData.period_length }}(s)
                      </span>
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Empty State -->
          <div
            v-else-if="!loading && !reportData"
            class="bg-white rounded-lg shadow-sm border border-slate-200 p-8 text-center"
          >
            <FileText class="mx-auto h-12 w-12 text-gray-400" />
            <h3 class="mt-2 text-sm font-medium text-gray-900">No report data available</h3>
            <p class="mt-1 text-sm text-gray-500">
              Select a date range and click Refresh to load the report.
            </p>
          </div>

          <!-- Loading State -->
          <div
            v-if="loading"
            class="bg-white rounded-lg shadow-sm border border-slate-200 p-8 text-center"
          >
            <RefreshCw class="mx-auto h-12 w-12 text-gray-400 animate-spin" />
            <p class="mt-2 text-sm text-gray-500">Loading profit & loss report...</p>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  FileText,
  Download,
  RefreshCw,
  DollarSign,
  AlertCircle,
  TrendingUp,
  BarChart3,
  X,
  Info,
} from 'lucide-vue-next'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { profitLossReportService } from '@/services/profit-loss-report.service'
import type {
  ProfitLossReportResponse,
  ProfitLossParams,
  PeriodPreset,
  PeriodLength,
} from '@/types/profit-loss.types'
import { toLocalDateString } from '@/utils/dateUtils'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { useFinancialYear } from '@/composables/useFinancialYear'

const companyDefaultsStore = useCompanyDefaultsStore()
const { getDateRange: getFyDateRange } = useFinancialYear()

const loading = ref(false)
const error = ref<string | null>(null)
const reportData = ref<ProfitLossReportResponse | null>(null)
const selectedPreset = ref<PeriodPreset | null>(null)

const dateRange = ref({
  startDate: '',
  endDate: '',
})

const comparison = ref({
  periods: 0,
  periodLength: 'month' as PeriodLength,
})

const summary = computed(() => {
  if (!reportData.value) return null

  const totalRevenue = reportData.value.revenue.total
  const grossProfit = reportData.value.gross_profit.amount
  const netProfit = reportData.value.net_profit.amount

  const grossProfitMargin = totalRevenue !== 0 ? (grossProfit / totalRevenue) * 100 : 0
  const netProfitMargin = totalRevenue !== 0 ? (netProfit / totalRevenue) * 100 : 0

  return {
    totalRevenue,
    grossProfit,
    netProfit,
    grossProfitMargin,
    netProfitMargin,
  }
})

const formatCurrency = (value: number): string => {
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

const formatPercentage = (percentage: number): string => {
  return `${percentage.toFixed(1)}%`
}

const formatDateRangeHeader = (startDate: string, endDate: string): string => {
  const start = new Date(startDate)
  const end = new Date(endDate)
  const formatDate = (d: Date) =>
    d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
  return `${formatDate(start)} - ${formatDate(end)}`
}

const setDateRange = (preset: PeriodPreset) => {
  selectedPreset.value = preset
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth()

  switch (preset) {
    case 'thisMonth':
      dateRange.value.startDate = toLocalDateString(new Date(year, month, 1))
      dateRange.value.endDate = toLocalDateString(new Date(year, month + 1, 0))
      break
    case 'lastMonth':
      dateRange.value.startDate = toLocalDateString(new Date(year, month - 1, 1))
      dateRange.value.endDate = toLocalDateString(new Date(year, month, 0))
      break
    case 'thisQuarter':
      const quarterStart = Math.floor(month / 3) * 3
      dateRange.value.startDate = toLocalDateString(new Date(year, quarterStart, 1))
      dateRange.value.endDate = toLocalDateString(new Date(year, quarterStart + 3, 0))
      break
    case 'lastQuarter':
      const lastQuarterStart = Math.floor((month - 3) / 3) * 3
      const lastQuarterYear = month < 3 ? year - 1 : year
      dateRange.value.startDate = toLocalDateString(new Date(lastQuarterYear, lastQuarterStart, 1))
      dateRange.value.endDate = toLocalDateString(
        new Date(lastQuarterYear, lastQuarterStart + 3, 0),
      )
      break
    case 'thisFinancialYear':
    case 'lastFinancialYear': {
      const range = getFyDateRange(preset)
      dateRange.value.startDate = range.startDate
      dateRange.value.endDate = range.endDate
      break
    }
    case 'monthToDate':
      dateRange.value.startDate = toLocalDateString(new Date(year, month, 1))
      dateRange.value.endDate = toLocalDateString(now)
      break
    case 'yearToDate':
      dateRange.value.startDate = toLocalDateString(new Date(year, 0, 1))
      dateRange.value.endDate = toLocalDateString(now)
      break
  }
  loadData()
}

const clearComparison = () => {
  comparison.value.periods = 0
  loadData()
}

const loadData = async () => {
  if (!dateRange.value.startDate || !dateRange.value.endDate) return

  try {
    loading.value = true
    error.value = null

    const params: ProfitLossParams = {
      start_date: dateRange.value.startDate,
      end_date: dateRange.value.endDate,
    }

    if (comparison.value.periods > 0) {
      params.compare_periods = comparison.value.periods
      params.period_length = comparison.value.periodLength
    }

    const response = await profitLossReportService.getProfitLossReport(params)
    reportData.value = response
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load profit & loss report'
    reportData.value = null
  } finally {
    loading.value = false
  }
}

const refreshData = () => {
  loadData()
}

const exportToCsv = () => {
  if (!reportData.value) return

  const headers = [
    'Account Code',
    'Account Name',
    formatDateRangeHeader(reportData.value.start_date, reportData.value.end_date),
    ...(reportData.value.compare_period_labels || []),
  ]

  const rows: string[][] = []

  // Revenue section
  rows.push(['', 'REVENUE', '', ...Array(headers.length - 3).fill('')])
  reportData.value.revenue.line_items.forEach((item) => {
    rows.push([
      item.account_code,
      item.account_name,
      item.amount.toFixed(2),
      ...(item.compare_amounts?.map((a) => a.toFixed(2)) || []),
    ])
  })
  rows.push([
    '',
    'Total Revenue',
    reportData.value.revenue.total.toFixed(2),
    ...(reportData.value.revenue.compare_totals?.map((t) => t.toFixed(2)) || []),
  ])

  // Cost of Sales section
  rows.push(['', '', '', ...Array(headers.length - 3).fill('')])
  rows.push(['', 'COST OF SALES', '', ...Array(headers.length - 3).fill('')])
  reportData.value.cost_of_sales.line_items.forEach((item) => {
    rows.push([
      item.account_code,
      item.account_name,
      item.amount.toFixed(2),
      ...(item.compare_amounts?.map((a) => a.toFixed(2)) || []),
    ])
  })
  rows.push([
    '',
    'Total Cost of Sales',
    reportData.value.cost_of_sales.total.toFixed(2),
    ...(reportData.value.cost_of_sales.compare_totals?.map((t) => t.toFixed(2)) || []),
  ])

  // Gross Profit
  rows.push(['', '', '', ...Array(headers.length - 3).fill('')])
  rows.push([
    '',
    'GROSS PROFIT',
    reportData.value.gross_profit.amount.toFixed(2),
    ...(reportData.value.gross_profit.compare_amounts?.map((a) => a.toFixed(2)) || []),
  ])

  // Operating Expenses section
  rows.push(['', '', '', ...Array(headers.length - 3).fill('')])
  rows.push(['', 'OPERATING EXPENSES', '', ...Array(headers.length - 3).fill('')])
  reportData.value.operating_expenses.line_items.forEach((item) => {
    rows.push([
      item.account_code,
      item.account_name,
      item.amount.toFixed(2),
      ...(item.compare_amounts?.map((a) => a.toFixed(2)) || []),
    ])
  })
  rows.push([
    '',
    'Total Operating Expenses',
    reportData.value.operating_expenses.total.toFixed(2),
    ...(reportData.value.operating_expenses.compare_totals?.map((t) => t.toFixed(2)) || []),
  ])

  // Net Profit
  rows.push(['', '', '', ...Array(headers.length - 3).fill('')])
  rows.push([
    '',
    'NET PROFIT',
    reportData.value.net_profit.amount.toFixed(2),
    ...(reportData.value.net_profit.compare_amounts?.map((a) => a.toFixed(2)) || []),
  ])

  const csvContent = [headers, ...rows].map((row) => row.join(',')).join('\n')

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)

  link.setAttribute('href', url)
  link.setAttribute(
    'download',
    `profit-loss-report-${dateRange.value.startDate}-to-${dateRange.value.endDate}.csv`,
  )
  link.style.visibility = 'hidden'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

onMounted(async () => {
  if (!companyDefaultsStore.isLoaded) {
    await companyDefaultsStore.loadCompanyDefaults()
  }
  // Set default to this month
  setDateRange('thisMonth')
})
</script>
