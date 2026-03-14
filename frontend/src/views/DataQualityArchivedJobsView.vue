<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <AlertTriangle class="w-8 h-8 text-amber-500" />
              Archived Jobs Validation
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportReport"
                :disabled="loading || !issues.length"
                class="text-sm px-4 py-2"
              >
                <Download class="w-4 h-4 mr-2" />
                Export CSV
              </Button>
              <Button
                variant="outline"
                @click="refreshData"
                :disabled="loading"
                class="text-sm px-4 py-2"
              >
                <RefreshCw class="w-4 h-4 mr-2" :class="{ 'animate-spin': loading }" />
                Refresh
              </Button>
            </div>
          </div>

          <!-- Summary Stats -->
          <div class="grid grid-cols-1 md:grid-cols-5 gap-4">
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center gap-3">
                <Archive class="w-5 h-5 text-slate-500" />
                <div>
                  <p class="text-sm text-slate-600">Total Archived</p>
                  <p class="text-2xl font-bold">{{ stats.totalArchived }}</p>
                </div>
              </div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center gap-3">
                <CheckCircle class="w-5 h-5 text-green-500" />
                <div>
                  <p class="text-sm text-slate-600">Valid</p>
                  <p class="text-2xl font-bold text-green-600">{{ stats.valid }}</p>
                </div>
              </div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center gap-3">
                <AlertCircle class="w-5 h-5 text-amber-500" />
                <div>
                  <p class="text-sm text-slate-600">Issues Found</p>
                  <p class="text-2xl font-bold text-amber-600">{{ stats.issuesFound }}</p>
                </div>
              </div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center gap-3">
                <Clock class="w-5 h-5 text-slate-500" />
                <div>
                  <p class="text-sm text-slate-600">Archived Since</p>
                  <p class="text-sm font-semibold">{{ archivedSince }}</p>
                </div>
              </div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center gap-3">
                <Clock class="w-5 h-5 text-slate-500" />
                <div>
                  <p class="text-sm text-slate-600">Last Run</p>
                  <p class="text-sm font-semibold">{{ lastRunTime }}</p>
                </div>
              </div>
            </div>
          </div>

          <!-- Issue Categories -->
          <div
            v-if="!loading && summary && Object.values(summary).some((v) => v > 0)"
            class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
          >
            <h2 class="text-lg font-semibold mb-3 text-slate-800">Issues by Type</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
              <div
                v-if="summary.not_invoiced > 0"
                class="flex items-center justify-between p-3 bg-slate-50 rounded-md"
              >
                <span class="text-sm font-medium text-slate-700">Not Invoiced</span>
                <span class="text-sm font-bold text-amber-600">{{ summary.not_invoiced }}</span>
              </div>
              <div
                v-if="summary.not_paid > 0"
                class="flex items-center justify-between p-3 bg-slate-50 rounded-md"
              >
                <span class="text-sm font-medium text-slate-700">Not Paid</span>
                <span class="text-sm font-bold text-amber-600">{{ summary.not_paid }}</span>
              </div>
              <div
                v-if="summary.not_cancelled > 0"
                class="flex items-center justify-between p-3 bg-slate-50 rounded-md"
              >
                <span class="text-sm font-medium text-slate-700">Not Cancelled</span>
                <span class="text-sm font-bold text-amber-600">{{ summary.not_cancelled }}</span>
              </div>
              <div
                v-if="summary.has_open_tasks > 0"
                class="flex items-center justify-between p-3 bg-slate-50 rounded-md"
              >
                <span class="text-sm font-medium text-slate-700">Has Open Tasks</span>
                <span class="text-sm font-bold text-amber-600">{{ summary.has_open_tasks }}</span>
              </div>
            </div>
          </div>

          <!-- Loading State -->
          <div
            v-if="loading"
            class="flex-1 flex items-center justify-center text-2xl text-slate-400"
          >
            <RefreshCw class="w-8 h-8 animate-spin mr-2" />
            Loading validation report...
          </div>

          <!-- Error State -->
          <div
            v-else-if="error"
            class="flex-1 flex items-center justify-center text-xl text-red-500"
          >
            <AlertCircle class="w-8 h-8 mr-2" />
            {{ error }}
          </div>

          <!-- No Issues State -->
          <div
            v-else-if="!loading && issues.length === 0"
            class="flex-1 flex items-center justify-center"
          >
            <div class="text-center">
              <CheckCircle class="w-16 h-16 text-green-500 mx-auto mb-4" />
              <h2 class="text-2xl font-semibold text-slate-800 mb-2">All Clear!</h2>
              <p class="text-slate-600">No validation issues found with archived jobs.</p>
            </div>
          </div>

          <!-- Issues Table -->
          <div
            v-else-if="!loading && issues.length > 0"
            class="flex-1 bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden flex flex-col"
          >
            <div class="p-4 border-b border-slate-200">
              <h2 class="text-lg font-semibold text-slate-800">
                Validation Issues ({{ issues.length }})
              </h2>
            </div>
            <div class="overflow-auto flex-1">
              <table class="w-full">
                <thead class="bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th
                      class="text-left px-4 py-3 text-sm font-semibold text-slate-700 cursor-pointer hover:bg-slate-100 select-none"
                      @click="handleSort('jobNumber')"
                    >
                      <div class="flex items-center gap-1">
                        Job Number
                        <span v-if="sortColumn === 'jobNumber'" class="text-slate-500">
                          {{ sortDirection === 'asc' ? '↑' : '↓' }}
                        </span>
                      </div>
                    </th>
                    <th
                      class="text-left px-4 py-3 text-sm font-semibold text-slate-700 cursor-pointer hover:bg-slate-100 select-none"
                      @click="handleSort('clientName')"
                    >
                      <div class="flex items-center gap-1">
                        Client
                        <span v-if="sortColumn === 'clientName'" class="text-slate-500">
                          {{ sortDirection === 'asc' ? '↑' : '↓' }}
                        </span>
                      </div>
                    </th>
                    <th
                      class="text-left px-4 py-3 text-sm font-semibold text-slate-700 cursor-pointer hover:bg-slate-100 select-none"
                      @click="handleSort('details')"
                    >
                      <div class="flex items-center gap-1">
                        Issue
                        <span v-if="sortColumn === 'details'" class="text-slate-500">
                          {{ sortDirection === 'asc' ? '↑' : '↓' }}
                        </span>
                      </div>
                    </th>
                    <th
                      class="text-left px-4 py-3 text-sm font-semibold text-slate-700 cursor-pointer hover:bg-slate-100 select-none"
                      @click="handleSort('archivedDate')"
                    >
                      <div class="flex items-center gap-1">
                        Archived Date
                        <span v-if="sortColumn === 'archivedDate'" class="text-slate-500">
                          {{ sortDirection === 'asc' ? '↑' : '↓' }}
                        </span>
                      </div>
                    </th>
                    <th
                      class="text-right px-4 py-3 text-sm font-semibold text-slate-700 cursor-pointer hover:bg-slate-100 select-none"
                      @click="handleSort('jobValue')"
                    >
                      <div class="flex items-center justify-end gap-1">
                        Job Value
                        <span v-if="sortColumn === 'jobValue'" class="text-slate-500">
                          {{ sortDirection === 'asc' ? '↑' : '↓' }}
                        </span>
                      </div>
                    </th>
                    <th class="text-center px-4 py-3 text-sm font-semibold text-slate-700">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-200">
                  <tr v-for="issue in sortedIssues" :key="issue.id" class="hover:bg-slate-50">
                    <td class="px-4 py-3 text-sm font-medium text-slate-900">
                      {{ issue.jobNumber }}
                    </td>
                    <td class="px-4 py-3 text-sm text-slate-700">
                      {{ issue.clientName }}
                    </td>
                    <td class="px-4 py-3">
                      <span
                        :class="getIssueClass(issue.details)"
                        class="px-2 py-1 text-xs font-medium rounded-full"
                      >
                        {{ issue.details }}
                      </span>
                    </td>
                    <td class="px-4 py-3 text-sm text-slate-600">
                      {{ formatDate(issue.archivedDate) }}
                    </td>
                    <td class="px-4 py-3 text-sm text-slate-900 text-right font-medium">
                      {{ formatCurrency(issue.jobValue) }}
                    </td>
                    <td class="px-4 py-3 text-center">
                      <RouterLink
                        :to="`/jobs/${issue.jobId}`"
                        class="text-indigo-600 hover:text-indigo-800 text-sm font-medium"
                      >
                        View Job
                      </RouterLink>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import AppLayout from '@/components/AppLayout.vue'
import Button from '@/components/ui/button/Button.vue'
import {
  AlertTriangle,
  RefreshCw,
  Download,
  Archive,
  CheckCircle,
  AlertCircle,
  Clock,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { formatCurrency, exportToCsv } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'

interface ValidationIssue {
  id: string
  jobId: string
  jobNumber: string
  clientName: string
  type:
    | 'open_timesheets'
    | 'incomplete_costs'
    | 'missing_invoices'
    | 'invalid_status'
    | 'open_tasks'
  details: string
  archivedDate: string
  jobValue: number
}

const loading = ref(false)
const error = ref<string | null>(null)
const issues = ref<ValidationIssue[]>([])
const lastRunTime = ref<string>('Never')
const archivedSince = ref<string>('N/A')
const totalRecords = ref<number>(0)
const failedRecords = ref<number>(0)
const summary = ref<{
  not_invoiced: number
  not_paid: number
  not_cancelled: number
  has_open_tasks: number
} | null>(null)

// Sorting state
const sortColumn = ref<keyof ValidationIssue | null>(null)
const sortDirection = ref<'asc' | 'desc'>('asc')

const stats = computed(() => {
  return {
    totalArchived: totalRecords.value,
    valid: totalRecords.value - failedRecords.value,
    issuesFound: failedRecords.value,
  }
})

// Computed property for sorted issues
const sortedIssues = computed(() => {
  if (!sortColumn.value) return issues.value

  return [...issues.value].sort((a, b) => {
    const aVal = a[sortColumn.value as keyof ValidationIssue]
    const bVal = b[sortColumn.value as keyof ValidationIssue]

    let comparison = 0
    if (aVal < bVal) comparison = -1
    if (aVal > bVal) comparison = 1

    return sortDirection.value === 'asc' ? comparison : -comparison
  })
})

// Function to handle column header clicks
const handleSort = (column: keyof ValidationIssue) => {
  if (sortColumn.value === column) {
    // Toggle direction if same column
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    // New column, default to ascending
    sortColumn.value = column
    sortDirection.value = 'asc'
  }
}

const getIssueClass = (issue: string): string => {
  if (issue.toLowerCase().includes('not invoiced')) return 'bg-amber-100 text-amber-800'
  if (issue.toLowerCase().includes('not paid')) return 'bg-orange-100 text-orange-800'
  if (issue.toLowerCase().includes('not cancelled')) return 'bg-red-100 text-red-800'
  if (issue.toLowerCase().includes('open tasks')) return 'bg-blue-100 text-blue-800'
  return 'bg-gray-100 text-gray-800'
}

const formatDate = (dateString: string): string => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleDateString('en-AU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

const mapIssueLabelToType = (issue?: string): ValidationIssue['type'] => {
  const normalized = issue?.toLowerCase() ?? ''
  if (normalized.includes('timesheet')) return 'open_timesheets'
  if (normalized.includes('cost')) return 'incomplete_costs'
  if (normalized.includes('invoice')) return 'missing_invoices'
  if (normalized.includes('status')) return 'invalid_status'
  if (normalized.includes('task')) return 'open_tasks'
  return 'invalid_status'
}

const refreshData = async () => {
  loading.value = true
  error.value = null

  try {
    const data = await api.get('/job/rest/data-quality/archived-jobs-compliance/')

    // Update statistics from the new structure
    totalRecords.value = data?.total_archived_jobs || 0
    failedRecords.value = data?.non_compliant_jobs?.length || 0

    // Update summary if provided
    if (data.summary) {
      summary.value = data.summary
    }

    // Map non_compliant_jobs to our display format
    if (data.non_compliant_jobs && data.non_compliant_jobs.length > 0) {
      issues.value = data.non_compliant_jobs.map(
        (job: {
          job_id: string
          job_number: string
          client_name: string
          issue?: string
          archived_date: string
          job_value: number
        }) => ({
          id: job.job_id,
          jobId: job.job_id,
          jobNumber: job.job_number,
          clientName: job.client_name,
          type: mapIssueLabelToType(job.issue),
          details: job.issue || 'Issue details unavailable',
          archivedDate: job.archived_date,
          jobValue: job.job_value,
        }),
      )

      // Calculate earliest archived date
      const earliestDate = data.non_compliant_jobs.reduce(
        (earliest: string, job: { archived_date: string }) => {
          return !earliest || job.archived_date < earliest ? job.archived_date : earliest
        },
        '',
      )

      if (earliestDate) {
        archivedSince.value = formatDate(earliestDate)
      }
    } else {
      issues.value = []
      archivedSince.value = 'N/A'
    }

    // Use checked_at from response or current time
    if (data.checked_at) {
      lastRunTime.value = new Date(data.checked_at).toLocaleString('en-AU', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } else {
      lastRunTime.value = new Date().toLocaleString('en-AU', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    }

    // Show appropriate toast based on results
    if (data.non_compliant_jobs?.length === 0) {
      toast.success('All archived jobs are in valid states!')
    } else {
      toast.warning(`Found ${data.non_compliant_jobs.length} non-compliant archived jobs`)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load compliance report'
    toast.error('Failed to load compliance report')
  } finally {
    loading.value = false
  }
}

const exportReport = () => {
  if (!issues.value.length) return

  const headers = ['Job Number', 'Client', 'Issue', 'Archived Date', 'Job Value']
  const rows = issues.value.map((issue) => [
    issue.jobNumber,
    issue.clientName,
    issue.details,
    formatDate(issue.archivedDate),
    formatCurrency(issue.jobValue),
  ])

  exportToCsv(headers, rows, `archived-jobs-validation-${toLocalDateString()}`)
  toast.success('Report exported successfully')
}

onMounted(() => {
  refreshData()
})
</script>
