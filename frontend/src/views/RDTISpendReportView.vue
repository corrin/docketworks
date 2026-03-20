<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <FlaskConical class="w-8 h-8 text-indigo-400" />
              RDTI Spend Report
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportReport"
                :disabled="loading || !jobs.length"
                class="text-sm px-4 py-2"
              >
                <Download class="w-4 h-4 mr-2" />
                Export CSV
              </Button>
              <Button
                variant="default"
                @click="loadData"
                :disabled="loading"
                class="text-sm px-4 py-2"
              >
                <RefreshCw class="w-4 h-4 mr-2" :class="{ 'animate-spin': loading }" />
                Refresh
              </Button>
            </div>
          </div>

          <!-- Filters -->
          <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
            <div class="flex flex-wrap items-end gap-4">
              <div class="flex items-center gap-2">
                <label for="start-date" class="text-sm font-medium text-gray-700">
                  Start Date:
                </label>
                <input
                  id="start-date"
                  v-model="filters.startDate"
                  type="date"
                  class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
              <div class="flex items-center gap-2">
                <label for="end-date" class="text-sm font-medium text-gray-700"> End Date: </label>
                <input
                  id="end-date"
                  v-model="filters.endDate"
                  type="date"
                  class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
              <Button variant="default" size="sm" @click="loadData" :disabled="loading">
                Apply Filters
              </Button>
            </div>
            <div class="flex gap-2 mt-3">
              <Button variant="outline" size="sm" @click="setDateRange('thisFinancialYear')">
                This Financial Year
              </Button>
              <Button variant="outline" size="sm" @click="setDateRange('lastFinancialYear')">
                Last Financial Year
              </Button>
              <Button variant="outline" size="sm" @click="setDateRange('thisQuarter')">
                This Quarter
              </Button>
              <Button variant="outline" size="sm" @click="setDateRange('thisMonth')">
                This Month
              </Button>
            </div>
          </div>

          <!-- Summary Cards -->
          <div
            v-if="totals && !loading"
            class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
          >
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <p class="text-sm font-medium text-gray-600">Total R&D Hours</p>
              <p class="text-2xl font-bold text-gray-900">
                {{ formatHoursDisplay(totals.hours) }}
              </p>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <p class="text-sm font-medium text-gray-600">Total R&D Cost</p>
              <p class="text-2xl font-bold text-gray-900">
                {{ formatCurrency(totals.cost) }}
              </p>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <p class="text-sm font-medium text-gray-600">Core R&D Cost</p>
              <p class="text-2xl font-bold text-gray-900">
                {{ formatCurrency(coreSummary?.cost ?? 0) }}
              </p>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <p class="text-sm font-medium text-gray-600">Supporting R&D Cost</p>
              <p class="text-2xl font-bold text-gray-900">
                {{ formatCurrency(supportingSummary?.cost ?? 0) }}
              </p>
            </div>
          </div>

          <!-- Loading State -->
          <div v-if="loading" class="flex items-center justify-center py-12">
            <RefreshCw class="h-8 w-8 animate-spin text-indigo-500" />
            <span class="ml-2 text-lg text-gray-600">Loading RDTI spend data...</span>
          </div>

          <!-- Error State -->
          <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="flex items-center">
              <AlertCircle class="h-5 w-5 text-red-400 mr-2" />
              <span class="text-red-800">{{ error }}</span>
            </div>
          </div>

          <!-- Data Table -->
          <div
            v-else-if="jobs.length > 0"
            class="bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden"
          >
            <div class="px-4 py-5 sm:p-6">
              <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                  <thead class="bg-gray-50">
                    <tr>
                      <th
                        class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100"
                        @click="handleSort('job_number')"
                      >
                        <div class="flex items-center gap-1">
                          Job #
                          <span v-if="sortColumn === 'job_number'" class="text-slate-500">
                            {{ sortDirection === 'asc' ? '↑' : '↓' }}
                          </span>
                        </div>
                      </th>
                      <th
                        class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100"
                        @click="handleSort('job_name')"
                      >
                        <div class="flex items-center gap-1">
                          Job Name
                          <span v-if="sortColumn === 'job_name'" class="text-slate-500">
                            {{ sortDirection === 'asc' ? '↑' : '↓' }}
                          </span>
                        </div>
                      </th>
                      <th
                        class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100"
                        @click="handleSort('client_name')"
                      >
                        <div class="flex items-center gap-1">
                          Client
                          <span v-if="sortColumn === 'client_name'" class="text-slate-500">
                            {{ sortDirection === 'asc' ? '↑' : '↓' }}
                          </span>
                        </div>
                      </th>
                      <th
                        class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100"
                        @click="handleSort('rdti_type')"
                      >
                        <div class="flex items-center gap-1">
                          RDTI Type
                          <span v-if="sortColumn === 'rdti_type'" class="text-slate-500">
                            {{ sortDirection === 'asc' ? '↑' : '↓' }}
                          </span>
                        </div>
                      </th>
                      <th
                        class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100"
                        @click="handleSort('hours')"
                      >
                        <div class="flex items-center justify-end gap-1">
                          Hours
                          <span v-if="sortColumn === 'hours'" class="text-slate-500">
                            {{ sortDirection === 'asc' ? '↑' : '↓' }}
                          </span>
                        </div>
                      </th>
                      <th
                        class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100"
                        @click="handleSort('cost')"
                      >
                        <div class="flex items-center justify-end gap-1">
                          Cost
                          <span v-if="sortColumn === 'cost'" class="text-slate-500">
                            {{ sortDirection === 'asc' ? '↑' : '↓' }}
                          </span>
                        </div>
                      </th>
                      <th
                        class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100"
                        @click="handleSort('revenue')"
                      >
                        <div class="flex items-center justify-end gap-1">
                          Revenue
                          <span v-if="sortColumn === 'revenue'" class="text-slate-500">
                            {{ sortDirection === 'asc' ? '↑' : '↓' }}
                          </span>
                        </div>
                      </th>
                    </tr>
                  </thead>
                  <tbody class="bg-white divide-y divide-gray-200">
                    <tr v-for="job in sortedJobs" :key="job.job_id" class="hover:bg-gray-50">
                      <td class="px-4 py-4 whitespace-nowrap text-sm">
                        <router-link
                          :to="`/jobs/${job.job_id}`"
                          class="text-indigo-600 hover:text-indigo-900 font-medium"
                        >
                          {{ job.job_number }}
                        </router-link>
                      </td>
                      <td
                        class="px-4 py-4 whitespace-nowrap text-sm text-gray-900 max-w-[200px] truncate"
                        :title="job.job_name"
                      >
                        {{ job.job_name }}
                      </td>
                      <td
                        class="px-4 py-4 whitespace-nowrap text-sm text-gray-900 max-w-[150px] truncate"
                        :title="job.client_name"
                      >
                        {{ job.client_name }}
                      </td>
                      <td class="px-4 py-4 whitespace-nowrap text-sm">
                        <span
                          class="inline-flex px-2 py-0.5 text-xs font-semibold rounded-full"
                          :class="
                            job.rdti_type === 'core'
                              ? 'bg-indigo-100 text-indigo-800'
                              : 'bg-amber-100 text-amber-800'
                          "
                        >
                          {{ job.rdti_type === 'core' ? 'Core' : 'Supporting' }}
                        </span>
                      </td>
                      <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ formatHoursDisplay(job.hours) }}
                      </td>
                      <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ formatCurrency(job.cost) }}
                      </td>
                      <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ formatCurrency(job.revenue) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <!-- Empty State -->
          <div v-else class="bg-white rounded-lg shadow-sm border border-slate-200 p-8 text-center">
            <FlaskConical class="mx-auto h-12 w-12 text-gray-400" />
            <h3 class="mt-2 text-sm font-medium text-gray-900">No RDTI spend data</h3>
            <p class="mt-1 text-sm text-gray-500">
              No RDTI classified jobs found for the selected date range. Try adjusting the filters.
            </p>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { FlaskConical, Download, RefreshCw, AlertCircle } from 'lucide-vue-next'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { api } from '@/api/client'
import { formatCurrency, formatHoursDisplay, exportToCsv } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'
import { toast } from 'vue-sonner'
import { useFinancialYear } from '@/composables/useFinancialYear'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'

type RDTISpendCategorySummary = z.infer<typeof schemas.RDTISpendCategorySummary>
type RDTISpendJobDetail = z.infer<typeof schemas.RDTISpendJobDetail>
type RDTISpendTotals = z.infer<typeof schemas.RDTISpendTotals>

const { getDateRange: getFyDateRange } = useFinancialYear()

const loading = ref(false)
const error = ref<string | null>(null)
const jobs = ref<RDTISpendJobDetail[]>([])
const summary = ref<RDTISpendCategorySummary[]>([])
const totals = ref<RDTISpendTotals | null>(null)

const filters = ref({
  startDate: '',
  endDate: '',
})

const coreSummary = computed(() => summary.value.find((s) => s.rdti_type === 'core'))
const supportingSummary = computed(() => summary.value.find((s) => s.rdti_type === 'supporting'))

type SortableColumn =
  | 'job_number'
  | 'job_name'
  | 'client_name'
  | 'rdti_type'
  | 'hours'
  | 'cost'
  | 'revenue'

const sortColumn = ref<SortableColumn | null>(null)
const sortDirection = ref<'asc' | 'desc'>('asc')

const getSortValue = (job: RDTISpendJobDetail, col: SortableColumn): string | number => {
  switch (col) {
    case 'job_number':
      return job.job_number
    case 'hours':
      return job.hours
    case 'cost':
      return job.cost
    case 'revenue':
      return job.revenue
    default:
      return job[col] ?? ''
  }
}

const sortedJobs = computed(() => {
  if (!sortColumn.value) return jobs.value

  return [...jobs.value].sort((a, b) => {
    const col = sortColumn.value as SortableColumn
    const aVal = getSortValue(a, col)
    const bVal = getSortValue(b, col)

    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return sortDirection.value === 'asc' ? aVal - bVal : bVal - aVal
    }

    const comparison = String(aVal).localeCompare(String(bVal))
    return sortDirection.value === 'asc' ? comparison : -comparison
  })
})

const handleSort = (column: SortableColumn) => {
  if (sortColumn.value === column) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = column
    sortDirection.value = 'asc'
  }
}

const setDateRange = (
  period: 'thisFinancialYear' | 'lastFinancialYear' | 'thisQuarter' | 'thisMonth',
) => {
  const now = new Date()

  switch (period) {
    case 'thisFinancialYear':
    case 'lastFinancialYear': {
      const range = getFyDateRange(period)
      filters.value.startDate = range.startDate
      filters.value.endDate = range.endDate
      break
    }
    case 'thisQuarter': {
      const quarterMonth = Math.floor(now.getMonth() / 3) * 3
      const start = new Date(now.getFullYear(), quarterMonth, 1)
      filters.value.startDate = toLocalDateString(start)
      filters.value.endDate = toLocalDateString(now)
      break
    }
    case 'thisMonth': {
      const start = new Date(now.getFullYear(), now.getMonth(), 1)
      filters.value.startDate = toLocalDateString(start)
      filters.value.endDate = toLocalDateString(now)
      break
    }
  }
  loadData()
}

const loadData = async () => {
  if (!filters.value.startDate || !filters.value.endDate) return

  loading.value = true
  error.value = null

  try {
    const response = await api.accounting_reports_rdti_spend_retrieve({
      queries: { start_date: filters.value.startDate, end_date: filters.value.endDate },
    })

    jobs.value = response.jobs
    summary.value = response.summary
    totals.value = response.totals
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load RDTI spend data'
    jobs.value = []
    summary.value = []
    totals.value = null
    toast.error('Failed to load RDTI spend report')
  } finally {
    loading.value = false
  }
}

const exportReport = () => {
  if (!jobs.value.length) return

  const headers = ['Job Number', 'Job Name', 'Client', 'RDTI Type', 'Hours', 'Cost', 'Revenue']

  const rows = jobs.value.map((job) => [
    job.job_number,
    job.job_name,
    job.client_name,
    job.rdti_type,
    job.hours,
    job.cost,
    job.revenue,
  ])

  exportToCsv(headers, rows, `rdti-spend-report-${toLocalDateString()}`)
  toast.success('Report exported successfully')
}

onMounted(() => {
  setDateRange('thisFinancialYear')
})
</script>
