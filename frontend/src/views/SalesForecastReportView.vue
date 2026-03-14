<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1
              data-automation-id="SalesForecastReport-title"
              class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3"
            >
              <TrendingUp class="w-8 h-8 text-indigo-400" />
              Sales Forecast Report
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportToCsv"
                :disabled="loading || !months.length"
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

          <!-- Description (hidden when month selected) -->
          <div v-if="!selectedMonth" class="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div class="flex items-start gap-3">
              <Info class="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
              <div class="text-sm text-blue-800">
                <p class="font-medium mb-1">About This Report</p>
                <p>
                  Compares Xero invoice totals vs Job Manager revenue attribution by month to
                  identify unbilled work, revenue forecasting discrepancies, and invoicing patterns.
                </p>
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

          <!-- Summary Cards (hidden when month selected) -->
          <div
            v-if="summary && !selectedMonth"
            data-automation-id="SalesForecastReport-summary-cards"
            class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
          >
            <div
              data-automation-id="SalesForecastReport-xero-sales-card"
              class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
            >
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Total Xero Sales</p>
                  <p
                    data-automation-id="SalesForecastReport-xero-sales-value"
                    class="text-2xl font-bold text-gray-900"
                  >
                    {{ formatCurrency(summary.totalXeroSales) }}
                  </p>
                </div>
                <FileText class="h-8 w-8 text-blue-500" />
              </div>
            </div>

            <div
              data-automation-id="SalesForecastReport-jm-sales-card"
              class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
            >
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Total JM Sales</p>
                  <p
                    data-automation-id="SalesForecastReport-jm-sales-value"
                    class="text-2xl font-bold text-gray-900"
                  >
                    {{ formatCurrency(summary.totalJmSales) }}
                  </p>
                </div>
                <DollarSign class="h-8 w-8 text-green-500" />
              </div>
            </div>

            <div
              data-automation-id="SalesForecastReport-variance-card"
              class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
            >
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Total Variance</p>
                  <p
                    data-automation-id="SalesForecastReport-variance-value"
                    class="text-2xl font-bold"
                    :class="summary.totalVariance >= 0 ? 'text-green-600' : 'text-red-600'"
                  >
                    {{ formatCurrency(summary.totalVariance) }}
                  </p>
                </div>
                <TrendingUp
                  class="h-8 w-8"
                  :class="summary.totalVariance >= 0 ? 'text-green-500' : 'text-red-500'"
                />
              </div>
            </div>

            <div
              data-automation-id="SalesForecastReport-avg-variance-card"
              class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
            >
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Avg Variance %</p>
                  <p
                    data-automation-id="SalesForecastReport-avg-variance-value"
                    class="text-2xl font-bold"
                    :class="summary.avgVariancePct >= 0 ? 'text-green-600' : 'text-red-600'"
                  >
                    {{ formatPercentage(summary.avgVariancePct) }}
                  </p>
                </div>
                <BarChart3
                  class="h-8 w-8"
                  :class="summary.avgVariancePct >= 0 ? 'text-green-500' : 'text-red-500'"
                />
              </div>
            </div>
          </div>

          <!-- Full Data Table (when no month selected) -->
          <div
            v-if="!loading && months.length > 0 && !selectedMonth"
            data-automation-id="SalesForecastReport-table-container"
            class="flex-1 overflow-hidden flex flex-col"
          >
            <div
              class="bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden flex-1 flex flex-col"
            >
              <div class="overflow-x-auto flex-1">
                <table
                  data-automation-id="SalesForecastReport-table"
                  class="min-w-full divide-y divide-gray-200"
                >
                  <thead class="bg-gray-50 sticky top-0">
                    <tr>
                      <th
                        scope="col"
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Month
                      </th>
                      <th
                        scope="col"
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Xero Sales
                      </th>
                      <th
                        scope="col"
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        JM Sales
                      </th>
                      <th
                        scope="col"
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Variance
                      </th>
                      <th
                        scope="col"
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Variance %
                      </th>
                    </tr>
                  </thead>
                  <tbody class="bg-white divide-y divide-gray-200">
                    <tr
                      v-for="month in months"
                      :key="month.month"
                      class="hover:bg-gray-50 cursor-pointer transition-colors"
                      @click="selectMonth(month.month)"
                    >
                      <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {{ month.month_label }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-900">
                        {{ formatCurrency(month.xero_sales) }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-900">
                        {{ formatCurrency(month.jm_sales) }}
                      </td>
                      <td
                        class="px-6 py-4 whitespace-nowrap text-sm text-right font-medium"
                        :class="month.variance >= 0 ? 'text-green-600' : 'text-red-600'"
                      >
                        {{ formatCurrency(month.variance) }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-right">
                        <span
                          class="inline-flex px-2 py-1 text-xs font-semibold rounded-full"
                          :class="getVarianceBadgeClass(month.variance_pct)"
                        >
                          {{ formatPercentage(month.variance_pct) }}
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <!-- Compact Selected Month Summary (when month selected) -->
          <div
            v-if="selectedMonth && selectedMonthData"
            class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
          >
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-4">
                <Button variant="ghost" size="sm" @click="clearSelection" class="p-1">
                  <ChevronLeft class="w-5 h-5" />
                </Button>
                <div>
                  <h2 class="text-lg font-semibold text-gray-900">
                    {{ selectedMonthData.month_label }}
                  </h2>
                  <div class="flex items-center gap-4 text-sm text-gray-600 mt-1">
                    <span>Xero: {{ formatCurrency(selectedMonthData.xero_sales) }}</span>
                    <span>JM: {{ formatCurrency(selectedMonthData.jm_sales) }}</span>
                    <span
                      class="font-medium"
                      :class="selectedMonthData.variance >= 0 ? 'text-green-600' : 'text-red-600'"
                    >
                      Variance: {{ formatCurrency(selectedMonthData.variance) }} ({{
                        formatPercentage(selectedMonthData.variance_pct)
                      }})
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Month Detail Section -->
          <div
            v-if="selectedMonth && !loading"
            class="bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden flex-1 flex flex-col"
          >
            <div class="bg-gray-50 px-6 py-3 border-b border-gray-200">
              <h2 class="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <List class="w-4 h-4 text-indigo-500" />
                Invoice & Job Details
              </h2>
            </div>

            <!-- Detail Loading -->
            <div v-if="detailLoading" class="p-8 text-center">
              <RefreshCw class="mx-auto h-8 w-8 text-gray-400 animate-spin" />
              <p class="mt-2 text-sm text-gray-500">Loading month details...</p>
            </div>

            <!-- Detail Error -->
            <div
              v-else-if="detailError"
              class="p-4 bg-red-50 border-b border-red-200 flex items-start gap-3"
            >
              <AlertCircle class="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
              <div class="text-sm text-red-800">{{ detailError }}</div>
            </div>

            <!-- Detail Data -->
            <div v-else-if="detailData" class="overflow-x-auto flex-1">
              <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                  <tr>
                    <th
                      class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('job_start_date')"
                    >
                      <div class="flex items-center gap-1">
                        Job Start
                        <ArrowUp
                          v-if="sortField === 'job_start_date' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'job_start_date' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('date')"
                    >
                      <div class="flex items-center gap-1">
                        Job Finish
                        <ArrowUp
                          v-if="sortField === 'date' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'date' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('client_name')"
                    >
                      <div class="flex items-center gap-1">
                        Client
                        <ArrowUp
                          v-if="sortField === 'client_name' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'client_name' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('invoice_numbers')"
                    >
                      <div class="flex items-center gap-1">
                        Invoices
                        <ArrowUp
                          v-if="sortField === 'invoice_numbers' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'invoice_numbers' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('job_number')"
                    >
                      <div class="flex items-center gap-1">
                        Job
                        <ArrowUp
                          v-if="sortField === 'job_number' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'job_number' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('note')"
                    >
                      <div class="flex items-center gap-1">
                        Note
                        <ArrowUp
                          v-if="sortField === 'note' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'note' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('total_invoiced')"
                    >
                      <div class="flex items-center justify-end gap-1">
                        Xero Revenue
                        <ArrowUp
                          v-if="sortField === 'total_invoiced' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'total_invoiced' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('job_revenue')"
                    >
                      <div class="flex items-center justify-end gap-1">
                        JM Revenue
                        <ArrowUp
                          v-if="sortField === 'job_revenue' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'job_revenue' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('variance')"
                    >
                      <div class="flex items-center justify-end gap-1">
                        Variance
                        <ArrowUp
                          v-if="sortField === 'variance' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'variance' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                    <th
                      class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                      @click="toggleSort('variance_all_time')"
                    >
                      <div class="flex items-center justify-end gap-1">
                        All-Time Δ
                        <ArrowUp
                          v-if="sortField === 'variance_all_time' && sortDirection === 'asc'"
                          class="w-3 h-3"
                        />
                        <ArrowDown
                          v-else-if="sortField === 'variance_all_time' && sortDirection === 'desc'"
                          class="w-3 h-3"
                        />
                        <ArrowUpDown v-else class="w-3 h-3 text-gray-300" />
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                  <tr
                    v-for="(row, index) in sortedDetailRows"
                    :key="index"
                    class="hover:bg-gray-50"
                  >
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                      <template v-if="row.job_start_date">
                        {{ row.job_start_date }}
                      </template>
                      <span v-else class="text-gray-400">—</span>
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                      {{ row.date }}
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                      {{ row.client_name }}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-900">
                      <template v-if="row.invoice_numbers">
                        {{ row.invoice_numbers }}
                      </template>
                      <span v-else class="text-gray-400">—</span>
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                      <template v-if="row.job_id">
                        <RouterLink
                          :to="{ name: 'job-edit', params: { id: row.job_id } }"
                          class="text-indigo-600 hover:text-indigo-800 hover:underline"
                        >
                          {{ row.job_number }} - {{ row.job_name }}
                        </RouterLink>
                      </template>
                      <span v-else class="text-gray-400">—</span>
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-500">
                      <template v-if="row.note">
                        {{ row.note }}
                      </template>
                      <span v-else class="text-gray-300">—</span>
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-right text-gray-900">
                      <template v-if="row.total_invoiced > 0">
                        {{ formatCurrency(row.total_invoiced) }}
                      </template>
                      <span v-else class="text-gray-400">—</span>
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap text-sm text-right text-gray-900">
                      <template v-if="row.job_revenue > 0">
                        {{ formatCurrency(row.job_revenue) }}
                      </template>
                      <span v-else class="text-gray-400">—</span>
                    </td>
                    <td
                      class="px-4 py-3 whitespace-nowrap text-sm text-right font-medium"
                      :class="row.variance >= 0 ? 'text-green-600' : 'text-red-600'"
                    >
                      {{ formatCurrency(row.variance) }}
                    </td>
                    <td
                      class="px-4 py-3 whitespace-nowrap text-sm text-right font-medium"
                      :class="
                        row.variance_all_time === 0 || row.variance_all_time === null
                          ? 'text-gray-400'
                          : row.variance_all_time >= 0
                            ? 'text-green-600'
                            : 'text-red-600'
                      "
                    >
                      {{ formatCurrency(row.variance_all_time ?? 0) }}
                    </td>
                  </tr>
                </tbody>
              </table>

              <!-- Empty detail state -->
              <div v-if="detailData.rows.length === 0" class="p-8 text-center">
                <List class="mx-auto h-12 w-12 text-gray-400" />
                <p class="mt-2 text-sm text-gray-500">No invoice or job data for this month.</p>
              </div>
            </div>
          </div>

          <!-- Empty State -->
          <div
            v-else-if="!loading && months.length === 0"
            class="bg-white rounded-lg shadow-sm border border-slate-200 p-8 text-center"
          >
            <TrendingUp class="mx-auto h-12 w-12 text-gray-400" />
            <h3 class="mt-2 text-sm font-medium text-gray-900">No sales data available</h3>
            <p class="mt-1 text-sm text-gray-500">
              No sales data found. Try refreshing or check your data sources.
            </p>
          </div>

          <!-- Loading State -->
          <div
            v-if="loading"
            data-automation-id="SalesForecastReport-loading"
            class="bg-white rounded-lg shadow-sm border border-slate-200 p-8 text-center"
          >
            <RefreshCw class="mx-auto h-12 w-12 text-gray-400 animate-spin" />
            <p class="mt-2 text-sm text-gray-500">Loading sales forecast data...</p>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  TrendingUp,
  Download,
  RefreshCw,
  DollarSign,
  AlertCircle,
  Info,
  FileText,
  BarChart3,
  List,
  ChevronLeft,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
} from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { salesForecastReportService } from '@/services/sales-forecast-report.service'
import type {
  SalesForecastMonth,
  SalesForecastMonthDetailResponse,
} from '@/types/sales-forecast.types'
import { toLocalDateString } from '@/utils/dateUtils'

const loading = ref(false)
const error = ref<string | null>(null)
const months = ref<SalesForecastMonth[]>([])

const selectedMonth = ref<string | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)
const detailData = ref<SalesForecastMonthDetailResponse | null>(null)

type SortField =
  | 'date'
  | 'client_name'
  | 'invoice_numbers'
  | 'total_invoiced'
  | 'job_number'
  | 'job_start_date'
  | 'job_revenue'
  | 'variance'
  | 'variance_all_time'
  | 'note'
type SortDirection = 'asc' | 'desc'

const sortField = ref<SortField>('date')
const sortDirection = ref<SortDirection>('asc')

const toggleSort = (field: SortField) => {
  if (sortField.value === field) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortField.value = field
    sortDirection.value = 'asc'
  }
}

const sortedDetailRows = computed(() => {
  if (!detailData.value) return []

  const rows = [...detailData.value.rows]
  const dir = sortDirection.value === 'asc' ? 1 : -1

  return rows.sort((a, b) => {
    const field = sortField.value
    const aVal = a[field]
    const bVal = b[field]

    // Handle nulls
    if (aVal === null && bVal === null) return 0
    if (aVal === null) return dir
    if (bVal === null) return -dir

    // String comparison
    if (typeof aVal === 'string' && typeof bVal === 'string') {
      return aVal.localeCompare(bVal) * dir
    }

    // Number comparison
    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return (aVal - bVal) * dir
    }

    return 0
  })
})

const summary = computed(() => {
  if (months.value.length === 0) return null

  const totalXeroSales = months.value.reduce((sum, m) => sum + m.xero_sales, 0)
  const totalJmSales = months.value.reduce((sum, m) => sum + m.jm_sales, 0)
  const totalVariance = months.value.reduce((sum, m) => sum + m.variance, 0)
  const avgVariancePct =
    months.value.reduce((sum, m) => sum + m.variance_pct, 0) / months.value.length

  return {
    totalXeroSales,
    totalJmSales,
    totalVariance,
    avgVariancePct,
  }
})

const selectedMonthData = computed(() => {
  if (!selectedMonth.value) return null
  return months.value.find((m) => m.month === selectedMonth.value) || null
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

const getVarianceBadgeClass = (variancePct: number): string => {
  if (Math.abs(variancePct) < 10) {
    return 'bg-green-100 text-green-800'
  } else if (Math.abs(variancePct) < 25) {
    return 'bg-yellow-100 text-yellow-800'
  } else {
    return 'bg-red-100 text-red-800'
  }
}

const selectMonth = async (month: string) => {
  if (selectedMonth.value === month) {
    clearSelection()
    return
  }

  selectedMonth.value = month
  detailLoading.value = true
  detailError.value = null
  detailData.value = null

  try {
    detailData.value = await salesForecastReportService.getMonthDetail(month)
  } catch (err) {
    detailError.value = err instanceof Error ? err.message : 'Failed to load month details'
  } finally {
    detailLoading.value = false
  }
}

const clearSelection = () => {
  selectedMonth.value = null
  detailData.value = null
  detailError.value = null
}

const loadData = async () => {
  try {
    loading.value = true
    error.value = null

    const response = await salesForecastReportService.getSalesForecast()
    months.value = response.months
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load sales forecast data'
    months.value = []
  } finally {
    loading.value = false
  }
}

const refreshData = () => {
  loadData()
}

const exportToCsv = () => {
  if (months.value.length === 0) return

  const headers = ['Month', 'Xero Sales', 'JM Sales', 'Variance', 'Variance %']
  const rows = months.value.map((m) => [
    m.month_label,
    m.xero_sales.toFixed(2),
    m.jm_sales.toFixed(2),
    m.variance.toFixed(2),
    m.variance_pct.toFixed(1),
  ])

  const csvContent = [headers, ...rows].map((row) => row.join(',')).join('\n')

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)

  link.setAttribute('href', url)
  link.setAttribute('download', `sales-forecast-report-${toLocalDateString()}.csv`)
  link.style.visibility = 'hidden'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

onMounted(() => {
  loadData()
})
</script>
