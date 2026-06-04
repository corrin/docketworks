<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1
              data-automation-id="WIPReport-title"
              class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3"
            >
              <ClipboardList class="w-8 h-8 text-indigo-400" />
              WIP Report
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportCsv"
                :disabled="loading || !reportData"
                class="text-sm px-4 py-2"
              >
                <Download class="w-4 h-4 mr-2" />
                Export CSV
              </Button>
              <Button
                variant="default"
                @click="fetchData"
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
            <div class="flex flex-wrap items-center gap-4">
              <div class="flex items-center gap-2">
                <label class="text-sm font-medium text-gray-700">Report Date:</label>
                <input
                  v-model="reportDate"
                  type="date"
                  class="border border-gray-300 rounded-md px-3 py-2 text-sm"
                  @change="fetchData"
                />
              </div>
              <div class="flex items-center gap-2">
                <label class="text-sm font-medium text-gray-700">Valuation Method:</label>
                <select
                  v-model="method"
                  class="border border-gray-300 rounded-md px-3 py-2 text-sm"
                  @change="fetchData"
                >
                  <option value="revenue">Revenue</option>
                  <option value="cost">Cost</option>
                </select>
              </div>
            </div>
          </div>

          <!-- Loading State -->
          <div
            v-if="loading"
            data-automation-id="WIPReport-loading"
            class="flex-1 flex items-center justify-center text-2xl text-slate-400"
          >
            <RefreshCw class="w-8 h-8 animate-spin mr-2" />
            Loading WIP data...
          </div>

          <!-- Error State -->
          <div
            v-else-if="error"
            class="flex-1 flex items-center justify-center text-xl text-red-500"
          >
            <AlertCircle class="w-8 h-8 mr-2" />
            {{ error }}
          </div>

          <template v-else-if="reportData">
            <!-- Data Table -->
            <div
              class="overflow-x-auto rounded-2xl shadow-xl bg-white border border-slate-200 flex-1"
            >
              <!-- Desktop Table -->
              <table
                data-automation-id="WIPReport-table"
                class="hidden md:table min-w-full text-sm text-left"
              >
                <thead class="bg-indigo-50 text-indigo-800 sticky top-0 z-10">
                  <tr>
                    <th
                      v-for="column in tableColumns"
                      :key="column.key"
                      class="px-4 py-3 font-semibold cursor-pointer hover:bg-indigo-100"
                      :class="
                        column.align === 'right'
                          ? 'text-right'
                          : column.align === 'center'
                            ? 'text-center'
                            : 'text-left'
                      "
                      @click="column.sortable && sortBy(column.key)"
                    >
                      <div
                        class="flex items-center gap-2"
                        :class="column.align === 'right' ? 'justify-end' : ''"
                      >
                        {{ column.label }}
                        <template v-if="column.sortable">
                          <ChevronUp
                            v-if="sortColumn === column.key && sortDirection === 'asc'"
                            class="w-4 h-4"
                          />
                          <ChevronDown
                            v-else-if="sortColumn === column.key && sortDirection === 'desc'"
                            class="w-4 h-4"
                          />
                          <ChevronsUpDown v-else class="w-4 h-4 opacity-50" />
                        </template>
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100">
                  <tr
                    v-for="job in sortedJobs"
                    :key="job.job_number"
                    class="hover:bg-slate-50 transition-colors"
                  >
                    <td class="px-4 py-3 font-medium text-indigo-600">
                      {{ job.job_number }}
                    </td>
                    <td class="px-4 py-3">{{ job.client }}</td>
                    <td class="px-4 py-3">
                      <span
                        class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                        :class="getStatusBadgeClass(job.status)"
                      >
                        {{ job.status }}
                      </span>
                    </td>
                    <td class="px-4 py-3 text-right">
                      {{ formatCurrency(getTimeValue(job)) }}
                    </td>
                    <td class="px-4 py-3 text-right">
                      {{ formatCurrency(getMaterialValue(job)) }}
                    </td>
                    <td class="px-4 py-3 text-right">
                      {{ formatCurrency(getAdjustValue(job)) }}
                    </td>
                    <td class="px-4 py-3 text-right font-medium">
                      {{ formatCurrency(job.gross_wip) }}
                    </td>
                    <td class="px-4 py-3 text-right">
                      {{ formatCurrency(job.invoiced) }}
                    </td>
                    <td class="px-4 py-3 text-right font-bold">
                      {{ formatCurrency(job.net_wip) }}
                    </td>
                  </tr>
                </tbody>
              </table>

              <!-- Mobile Card View -->
              <div class="md:hidden space-y-4 p-4">
                <div
                  v-for="job in sortedJobs"
                  :key="job.job_number"
                  class="bg-white border border-slate-200 rounded-lg p-4 shadow-sm"
                >
                  <div class="flex justify-between items-start mb-3">
                    <div>
                      <div class="text-lg font-semibold text-indigo-600">#{{ job.job_number }}</div>
                      <div class="text-sm text-gray-600">{{ job.name }}</div>
                      <div class="text-sm text-gray-500">{{ job.client }}</div>
                    </div>
                    <span
                      class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                      :class="getStatusBadgeClass(job.status)"
                    >
                      {{ job.status }}
                    </span>
                  </div>

                  <div class="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <div class="font-medium text-gray-700">Gross WIP</div>
                      <div class="text-gray-600">{{ formatCurrency(job.gross_wip) }}</div>
                    </div>
                    <div>
                      <div class="font-medium text-gray-700">Invoiced</div>
                      <div class="text-gray-600">{{ formatCurrency(job.invoiced) }}</div>
                    </div>
                    <div>
                      <div class="font-medium text-gray-700">Net WIP</div>
                      <div class="font-bold text-gray-800">{{ formatCurrency(job.net_wip) }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Archived Jobs Note -->
            <div
              v-if="reportData.archived_jobs.length > 0"
              class="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800"
            >
              <AlertTriangle class="w-4 h-4 inline mr-1" />
              {{ reportData.archived_jobs.length }} archived job(s) with remaining WIP excluded from
              the table above.
            </div>

            <!-- Summary Section -->
            <div
              data-automation-id="WIPReport-summary"
              class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
            >
              <h2 class="text-lg font-semibold text-gray-800 mb-4">Summary</h2>
              <div
                data-automation-id="WIPReport-summary-cards"
                class="grid grid-cols-2 md:grid-cols-4 gap-4 text-center mb-6"
              >
                <div>
                  <div class="text-2xl font-bold text-indigo-600">
                    {{ reportData.summary.job_count }}
                  </div>
                  <div class="text-sm text-gray-600">Total Jobs</div>
                </div>
                <div>
                  <div
                    data-automation-id="WIPReport-total-gross-value"
                    class="text-2xl font-bold text-green-600"
                  >
                    {{ formatCurrency(reportData.summary.total_gross) }}
                  </div>
                  <div class="text-sm text-gray-600">Total Gross WIP</div>
                </div>
                <div>
                  <div class="text-2xl font-bold text-amber-600">
                    {{ formatCurrency(reportData.summary.total_invoiced) }}
                  </div>
                  <div class="text-sm text-gray-600">Total Invoiced</div>
                </div>
                <div>
                  <div
                    data-automation-id="WIPReport-total-net-value"
                    class="text-2xl font-bold text-blue-600"
                  >
                    {{ formatCurrency(reportData.summary.total_net) }}
                  </div>
                  <div class="text-sm text-gray-600">Total Net WIP</div>
                </div>
              </div>

              <!-- Breakdown by Status -->
              <div v-if="reportData.summary.by_status.length > 0">
                <h3 class="text-sm font-semibold text-gray-700 mb-2">Breakdown by Status</h3>
                <table class="min-w-full text-sm">
                  <thead class="bg-slate-50">
                    <tr>
                      <th class="px-4 py-2 text-left font-medium text-gray-600">Status</th>
                      <th class="px-4 py-2 text-right font-medium text-gray-600">Jobs</th>
                      <th class="px-4 py-2 text-right font-medium text-gray-600">Net WIP</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-slate-100">
                    <tr v-for="row in reportData.summary.by_status" :key="row.status">
                      <td class="px-4 py-2">
                        <span
                          class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                          :class="getStatusBadgeClass(row.status)"
                        >
                          {{ row.status }}
                        </span>
                      </td>
                      <td class="px-4 py-2 text-right">{{ row.count }}</td>
                      <td class="px-4 py-2 text-right font-medium">
                        {{ formatCurrency(row.net_wip) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import {
  ClipboardList,
  Download,
  RefreshCw,
  AlertCircle,
  AlertTriangle,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
} from 'lucide-vue-next'
import { wipReportService } from '@/services/wip-report.service'
import type { WIPReportResponse, WIPJobData } from '@/services/wip-report.service'
import { formatCurrency } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'

// Reactive state
const reportData = ref<WIPReportResponse | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const reportDate = ref(toLocalDateString())
const method = ref<'revenue' | 'cost'>('revenue')
const sortColumn = ref<string>('net_wip')
const sortDirection = ref<'asc' | 'desc'>('desc')

// Table configuration
interface TableColumn {
  key: string
  label: string
  sortable: boolean
  align?: 'left' | 'center' | 'right'
}

const tableColumns: TableColumn[] = [
  { key: 'job_number', label: 'Job #', sortable: true },
  { key: 'client', label: 'Client', sortable: true },
  { key: 'status', label: 'Status', sortable: true },
  { key: 'time', label: 'Time', sortable: true, align: 'right' },
  { key: 'material', label: 'Material', sortable: true, align: 'right' },
  { key: 'adjust', label: 'Adjust', sortable: true, align: 'right' },
  { key: 'gross_wip', label: 'Gross WIP', sortable: true, align: 'right' },
  { key: 'invoiced', label: 'Invoiced', sortable: true, align: 'right' },
  { key: 'net_wip', label: 'Net WIP', sortable: true, align: 'right' },
]

// Value accessors based on method
const getTimeValue = (job: WIPJobData): number =>
  method.value === 'revenue' ? job.time_rev : job.time_cost

const getMaterialValue = (job: WIPJobData): number =>
  method.value === 'revenue' ? job.material_rev : job.material_cost

const getAdjustValue = (job: WIPJobData): number =>
  method.value === 'revenue' ? job.adjust_rev : job.adjust_cost

// Sort helper
const getSortValue = (job: WIPJobData, key: string): number | string => {
  switch (key) {
    case 'time':
      return getTimeValue(job)
    case 'material':
      return getMaterialValue(job)
    case 'adjust':
      return getAdjustValue(job)
    case 'job_number':
      return job.job_number
    case 'client':
      return job.client
    case 'status':
      return job.status
    case 'gross_wip':
      return job.gross_wip
    case 'invoiced':
      return job.invoiced
    case 'net_wip':
      return job.net_wip
    default:
      return 0
  }
}

// Computed
const sortedJobs = computed(() => {
  if (!reportData.value) return []
  const jobs = reportData.value.jobs.slice()

  jobs.sort((a, b) => {
    const aVal = getSortValue(a, sortColumn.value)
    const bVal = getSortValue(b, sortColumn.value)

    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return sortDirection.value === 'asc' ? aVal - bVal : bVal - aVal
    }

    const aStr = String(aVal)
    const bStr = String(bVal)
    if (aStr < bStr) return sortDirection.value === 'asc' ? -1 : 1
    if (aStr > bStr) return sortDirection.value === 'asc' ? 1 : -1
    return 0
  })

  return jobs
})

// Methods
const fetchData = async () => {
  loading.value = true
  error.value = null

  try {
    reportData.value = await wipReportService.getWIPReport({
      date: reportDate.value,
      method: method.value,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load WIP report'
  } finally {
    loading.value = false
  }
}

const sortBy = (column: string) => {
  if (sortColumn.value === column) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = column
    sortDirection.value = 'asc'
  }
}

const exportCsv = () => {
  if (!reportData.value) return
  wipReportService.exportToFile(sortedJobs.value, method.value, reportData.value.report_date)
}

const getStatusBadgeClass = (status: string): string => {
  const statusClasses: Record<string, string> = {
    in_progress: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    on_hold: 'bg-yellow-100 text-yellow-800',
    cancelled: 'bg-red-100 text-red-800',
    approved: 'bg-purple-100 text-purple-800',
    quoting: 'bg-indigo-100 text-indigo-800',
  }
  return statusClasses[status] || 'bg-gray-100 text-gray-800'
}

// Lifecycle
onMounted(() => {
  fetchData()
})
</script>
