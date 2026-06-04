<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <ClockIcon class="w-8 h-8 text-indigo-400" />
              Job Aging Report
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportToCsv"
                :disabled="loading || !jobs.length"
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

          <!-- Filters -->
          <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
            <div class="flex flex-wrap items-center gap-4">
              <div class="flex items-center gap-2">
                <input
                  id="include-archived"
                  v-model="filters.includeArchived"
                  type="checkbox"
                  class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  @change="applyFilters"
                />
                <label for="include-archived" class="text-sm font-medium text-gray-700">
                  Include Archived Jobs
                </label>
              </div>

              <div class="flex items-center gap-2">
                <label class="text-sm font-medium text-gray-700">Status:</label>
                <select
                  v-model="filters.statusFilter"
                  multiple
                  class="border border-gray-300 rounded-md px-3 py-2 text-sm"
                  @change="applyFilters"
                >
                  <option value="">All Statuses</option>
                  <option v-for="status in uniqueStatuses" :key="status" :value="status">
                    {{ status }}
                  </option>
                </select>
              </div>

              <div class="flex items-center gap-2">
                <label class="text-sm font-medium text-gray-700">Last Activity:</label>
                <select
                  v-model="filters.lastActivityThreshold"
                  class="border border-gray-300 rounded-md px-3 py-2 text-sm"
                  @change="applyFilters"
                >
                  <option :value="null">All</option>
                  <option :value="7">7+ days</option>
                  <option :value="14">14+ days</option>
                  <option :value="30">30+ days</option>
                  <option :value="60">60+ days</option>
                </select>
              </div>
            </div>
          </div>

          <!-- Loading State -->
          <div
            v-if="loading"
            class="flex-1 flex items-center justify-center text-2xl text-slate-400"
          >
            <RefreshCw class="w-8 h-8 animate-spin mr-2" />
            Loading jobs...
          </div>

          <!-- Error State -->
          <div
            v-else-if="error"
            class="flex-1 flex items-center justify-center text-xl text-red-500"
          >
            <AlertCircle class="w-8 h-8 mr-2" />
            {{ error }}
          </div>

          <!-- Data Table -->
          <div
            v-else
            class="overflow-x-auto rounded-2xl shadow-xl bg-white border border-slate-200 flex-1"
          >
            <!-- Desktop Table -->
            <table class="hidden md:table min-w-full text-sm text-left">
              <thead class="bg-indigo-50 text-indigo-800 sticky top-0 z-10">
                <tr>
                  <th
                    v-for="column in tableColumns"
                    :key="column.key"
                    class="px-4 py-3 font-semibold cursor-pointer hover:bg-indigo-100"
                    :class="
                      column.align === 'center'
                        ? 'text-center'
                        : column.align === 'right'
                          ? 'text-right'
                          : 'text-left'
                    "
                    @click="column.sortable && sortBy(column.key)"
                  >
                    <div class="flex items-center gap-2">
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
                  v-for="job in sortedAndFilteredJobs"
                  :key="job.id"
                  class="hover:bg-slate-50 transition-colors"
                >
                  <td class="px-4 py-3">
                    <router-link
                      :to="`/jobs/${job.id}`"
                      class="text-indigo-600 hover:text-indigo-800 font-medium"
                    >
                      {{ job.job_number }}
                    </router-link>
                  </td>
                  <td class="px-4 py-3">
                    {{ job.name }}
                  </td>
                  <td class="px-4 py-3">
                    {{ job.client_name }}
                  </td>
                  <td class="px-4 py-3">
                    <span
                      class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                      :class="getStatusBadgeClass(job.status)"
                    >
                      {{ job.status_display }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-center">
                    <span
                      class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                      :class="getDaysInStatusClass(job.timing_data.days_in_current_status)"
                    >
                      {{ job.timing_data.days_in_current_status }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-center">
                    {{ job.timing_data.created_days_ago }}
                  </td>
                  <td class="px-4 py-3 text-center">
                    <div class="flex flex-col items-center">
                      <span
                        class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                        :class="getLastActivityClass(job.timing_data.last_activity_days_ago)"
                      >
                        {{ job.timing_data.last_activity_days_ago }} days
                      </span>
                      <span class="text-xs text-gray-500 mt-1">
                        {{ job.timing_data.last_activity_type }}
                      </span>
                    </div>
                  </td>
                  <td class="px-4 py-3 text-right">
                    <div class="text-xs">
                      <div>Est: {{ formatCurrency(job.financial_data.estimate_total) }}</div>
                      <div>Quote: {{ formatCurrency(job.financial_data.quote_total) }}</div>
                      <div>Actual: {{ formatCurrency(job.financial_data.actual_total) }}</div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>

            <!-- Mobile Card View -->
            <div class="md:hidden space-y-4 p-4">
              <div
                v-for="job in sortedAndFilteredJobs"
                :key="job.id"
                class="bg-white border border-slate-200 rounded-lg p-4 shadow-sm"
              >
                <div class="flex justify-between items-start mb-3">
                  <div>
                    <router-link
                      :to="`/jobs/${job.id}`"
                      class="text-lg font-semibold text-indigo-600 hover:text-indigo-800"
                    >
                      #{{ job.job_number }}
                    </router-link>
                    <div class="text-sm text-gray-600">{{ job.name }}</div>
                  </div>
                  <span
                    class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                    :class="getStatusBadgeClass(job.status)"
                  >
                    {{ job.status_display }}
                  </span>
                </div>

                <div class="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div class="font-medium text-gray-700">Client</div>
                    <div class="text-gray-600">{{ job.client_name }}</div>
                  </div>
                  <div>
                    <div class="font-medium text-gray-700">Job Age</div>
                    <div class="text-gray-600">{{ job.timing_data.created_days_ago }} days</div>
                  </div>
                  <div>
                    <div class="font-medium text-gray-700">Last Activity</div>
                    <div class="flex items-center gap-2">
                      <span
                        class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium"
                        :class="getLastActivityClass(job.timing_data.last_activity_days_ago)"
                      >
                        {{ job.timing_data.last_activity_days_ago }} days
                      </span>
                    </div>
                  </div>
                  <div>
                    <div class="font-medium text-gray-700">Days in Status</div>
                    <span
                      class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium"
                      :class="getDaysInStatusClass(job.timing_data.days_in_current_status)"
                    >
                      {{ job.timing_data.days_in_current_status }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Summary Stats -->
          <div
            v-if="!loading && !error"
            class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
          >
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
              <div>
                <div class="text-2xl font-bold text-indigo-600">
                  {{ sortedAndFilteredJobs.length }}
                </div>
                <div class="text-sm text-gray-600">Total Jobs</div>
              </div>
              <div>
                <div class="text-2xl font-bold text-amber-600">{{ staleJobsCount }}</div>
                <div class="text-sm text-gray-600">Stale Jobs (30+ days)</div>
              </div>
              <div>
                <div class="text-2xl font-bold text-green-600">{{ averageJobAge }}</div>
                <div class="text-sm text-gray-600">Avg Job Age (days)</div>
              </div>
              <div>
                <div class="text-2xl font-bold text-red-600">{{ noActivityCount }}</div>
                <div class="text-sm text-gray-600">No Activity (60+ days)</div>
              </div>
            </div>
          </div>
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
  ClockIcon,
  Download,
  RefreshCw,
  AlertCircle,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
} from 'lucide-vue-next'
import { jobAgingReportService } from '@/services/job-aging-report.service'
import type { JobAgingData, JobAgingFilters, JobAgingTableColumn } from '@/types/job-aging.types'
import { formatCurrency } from '@/utils/string-formatting'

// Reactive state
const jobs = ref<JobAgingData[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const sortColumn = ref<string>('timing_data.last_activity_days_ago')
const sortDirection = ref<'asc' | 'desc'>('desc')

// Filters
const filters = ref<JobAgingFilters>({
  includeArchived: false,
  statusFilter: [],
  ageRange: { min: 0, max: 999 },
  lastActivityThreshold: null,
})

// Table configuration
const tableColumns: JobAgingTableColumn[] = [
  { key: 'job_number', label: 'Job #', sortable: true },
  { key: 'name', label: 'Job Name', sortable: true },
  { key: 'client_name', label: 'Client', sortable: true },
  { key: 'status_display', label: 'Status', sortable: true },
  {
    key: 'timing_data.days_in_current_status',
    label: 'Days in Status',
    sortable: true,
    align: 'center',
  },
  { key: 'timing_data.created_days_ago', label: 'Job Age', sortable: true, align: 'center' },
  {
    key: 'timing_data.last_activity_days_ago',
    label: 'Last Activity',
    sortable: true,
    align: 'center',
  },
  { key: 'financial_data', label: 'Financial', sortable: false, align: 'right' },
]

// Computed properties
const uniqueStatuses = computed(() => {
  const statuses = new Set(jobs.value.map((job) => job.status_display))
  return Array.from(statuses).sort()
})

const sortedAndFilteredJobs = computed(() => {
  let filtered = jobs.value.slice()

  // Apply filters
  if (filters.value.statusFilter.length > 0) {
    filtered = filtered.filter(
      (job) =>
        filters.value.statusFilter.includes(job.status_display) ||
        filters.value.statusFilter.includes(''),
    )
  }

  if (filters.value.lastActivityThreshold !== null) {
    filtered = filtered.filter(
      (job) => job.timing_data.last_activity_days_ago >= filters.value.lastActivityThreshold!,
    )
  }

  // Apply sorting
  filtered.sort((a, b) => {
    const getValue = (job: JobAgingData, key: string): unknown => {
      const keys = key.split('.')
      let value: unknown = job
      for (const k of keys) {
        value = (value as Record<string, unknown>)[k]
      }
      return value
    }

    const aValue = getValue(a, sortColumn.value)
    const bValue = getValue(b, sortColumn.value)

    if (typeof aValue === 'number' && typeof bValue === 'number') {
      return sortDirection.value === 'asc' ? aValue - bValue : bValue - aValue
    }

    const aStr = String(aValue)
    const bStr = String(bValue)

    if (aStr < bStr) return sortDirection.value === 'asc' ? -1 : 1
    if (aStr > bStr) return sortDirection.value === 'asc' ? 1 : -1
    return 0
  })

  return filtered
})

const staleJobsCount = computed(() => {
  return sortedAndFilteredJobs.value.filter((job) => job.timing_data.last_activity_days_ago >= 30)
    .length
})

const averageJobAge = computed(() => {
  if (sortedAndFilteredJobs.value.length === 0) return 0
  const total = sortedAndFilteredJobs.value.reduce(
    (sum, job) => sum + job.timing_data.created_days_ago,
    0,
  )
  return Math.round(total / sortedAndFilteredJobs.value.length)
})

const noActivityCount = computed(() => {
  return sortedAndFilteredJobs.value.filter((job) => job.timing_data.last_activity_days_ago >= 60)
    .length
})

// Methods
const fetchData = async () => {
  loading.value = true
  error.value = null

  try {
    const response = await jobAgingReportService.getJobAgingReport({
      include_archived: filters.value.includeArchived,
    })
    jobs.value = response.jobs
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load data'
  } finally {
    loading.value = false
  }
}

const refreshData = () => {
  fetchData()
}

const applyFilters = () => {
  fetchData()
}

const sortBy = (column: string) => {
  if (sortColumn.value === column) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = column
    sortDirection.value = 'asc'
  }
}

const exportToCsv = () => {
  jobAgingReportService.exportToFile(sortedAndFilteredJobs.value)
}

const getStatusBadgeClass = (status: string): string => {
  const statusClasses: Record<string, string> = {
    in_progress: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    on_hold: 'bg-yellow-100 text-yellow-800',
    cancelled: 'bg-red-100 text-red-800',
    quote_sent: 'bg-purple-100 text-purple-800',
  }
  return statusClasses[status] || 'bg-gray-100 text-gray-800'
}

const getDaysInStatusClass = (days: number): string => {
  if (days > 30) return 'bg-red-100 text-red-800'
  if (days > 14) return 'bg-yellow-100 text-yellow-800'
  return 'bg-green-100 text-green-800'
}

const getLastActivityClass = (days: number): string => {
  if (days > 60) return 'bg-red-100 text-red-800'
  if (days > 30) return 'bg-yellow-100 text-yellow-800'
  if (days > 14) return 'bg-amber-100 text-amber-800'
  return 'bg-green-100 text-green-800'
}

// Lifecycle
onMounted(() => {
  fetchData()
})
</script>
