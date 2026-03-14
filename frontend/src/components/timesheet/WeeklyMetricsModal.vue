<template>
  <Dialog :open="isOpen" @update:open="handleOpenChange">
    <DialogContent
      class="!max-w-[95vw] sm:!max-w-5xl lg:!max-w-6xl xl:!max-w-7xl max-h-[90vh] w-full overflow-y-auto p-6"
    >
      <!-- Header -->
      <DialogHeader class="mb-6">
        <div class="flex items-center justify-between pr-16">
          <div class="flex items-center space-x-3">
            <DialogTitle class="text-xl font-bold text-gray-900">Weekly Metrics</DialogTitle>
          </div>

          <div class="flex items-center space-x-8">
            <!-- Detailed Mode Switch -->
            <div class="flex items-center space-x-3">
              <span class="text-sm font-medium text-gray-600">Detailed View</span>
              <button
                :disabled="isLoading"
                @click="toggleDetailedMode"
                :class="[
                  'relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
                  detailedMode ? 'bg-blue-600' : 'bg-gray-200',
                ]"
              >
                <span
                  :class="[
                    'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                    detailedMode ? 'translate-x-6' : 'translate-x-1',
                  ]"
                ></span>
              </button>
            </div>
          </div>
        </div>
      </DialogHeader>

      <!-- Loading State -->
      <div v-if="isLoading" class="flex items-center justify-center py-12">
        <div class="text-center space-y-4">
          <div
            class="h-8 w-8 mx-auto rounded-full border-4 border-gray-300 border-t-gray-600 animate-spin"
          ></div>
          <p class="text-gray-600 text-sm font-medium">Loading weekly metrics...</p>
        </div>
      </div>

      <div v-else-if="!isLoading">
        <!-- Simple View: Clean Summary -->
        <div v-if="!detailedMode" class="space-y-6">
          <!-- Weekly Summary Cards -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <!-- Total Hours -->
            <div class="bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
              <p class="text-sm font-medium text-gray-600 mb-1">Total Hours</p>
              <p class="text-2xl font-bold text-gray-900">
                {{ weeklyData?.weekly_summary?.total_hours || 0 }}
              </p>
            </div>

            <!-- Total Staff -->
            <div class="bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
              <p class="text-sm font-medium text-gray-600 mb-1">Staff Count</p>
              <p class="text-2xl font-bold text-gray-900">
                {{ weeklyData?.weekly_summary?.staff_count || 0 }}
              </p>
            </div>

            <!-- Billable Percentage -->
            <div class="bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
              <p class="text-sm font-medium text-gray-600 mb-1">Billable %</p>
              <p class="text-2xl font-bold text-gray-900">
                {{ Math.round(weeklyData?.weekly_summary?.billable_percentage || 0) }}%
              </p>
            </div>

            <!-- Active Jobs -->
            <div class="bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
              <p class="text-sm font-medium text-gray-600 mb-1">Active Jobs</p>
              <p class="text-2xl font-bold text-gray-900">{{ activeJobsCount }}</p>
            </div>
          </div>

          <!-- Financial Summary -->
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <!-- Estimated Profit -->
            <div class="bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
              <p class="text-sm font-medium text-gray-600 mb-1">Estimated Profit</p>
              <p class="text-xl font-bold text-gray-900">
                ${{ formatCurrency(totalEstimatedProfit) }}
              </p>
              <p class="text-xs text-gray-500 mt-1">For this week</p>
            </div>

            <!-- Actual Profit -->
            <div class="bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
              <p class="text-sm font-medium text-gray-600 mb-1">Actual Profit</p>
              <p class="text-xl font-bold text-gray-900">
                ${{ formatCurrency(totalActualProfit) }}
              </p>
              <p class="text-xs text-gray-500 mt-1">For this week</p>
            </div>

            <!-- Total Profit -->
            <div class="p-4 rounded-lg border shadow-sm" :class="getProfitComparisonClass()">
              <p class="text-sm font-medium text-gray-600 mb-1">Total Profit</p>
              <p class="text-xl font-bold text-gray-900">${{ formatCurrency(totalProfit) }}</p>
              <p class="text-xs text-gray-500 mt-1">
                {{ totalProfit >= totalEstimatedProfit ? 'Above' : 'Below' }} estimated
              </p>
            </div>
          </div>

          <!-- Staff Completion Status -->
          <div class="bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
            <h4 class="text-lg font-semibold text-gray-900 mb-4">Staff Completion Status</h4>
            <div class="grid grid-cols-3 gap-6">
              <div class="text-center p-3 rounded-lg bg-green-50 border border-green-200">
                <p class="text-2xl font-bold text-green-800 mb-1">
                  {{ staffCompletionStats.complete }}
                </p>
                <p class="text-sm text-green-600">Complete (≥40h)</p>
              </div>
              <div class="text-center p-3 rounded-lg bg-yellow-50 border border-yellow-200">
                <p class="text-2xl font-bold text-yellow-800 mb-1">
                  {{ staffCompletionStats.partial }}
                </p>
                <p class="text-sm text-yellow-600">Partial (&lt;40h)</p>
              </div>
              <div class="text-center p-3 rounded-lg bg-red-50 border border-red-200">
                <p class="text-2xl font-bold text-red-800 mb-1">
                  {{ staffCompletionStats.missing }}
                </p>
                <p class="text-sm text-red-600">No Hours</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Detailed View: Compact Job Analysis -->
        <div v-else class="space-y-6">
          <!-- Legend -->
          <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">
            <h4 class="text-sm font-semibold text-gray-900 mb-3">Job Status Legend</h4>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div class="flex items-center space-x-3">
                <div class="w-6 h-4 rounded bg-green-50 border border-green-200"></div>
                <span class="text-gray-700">Healthy: Profitable with hours on track</span>
              </div>
              <div class="flex items-center space-x-3">
                <div class="w-6 h-4 rounded bg-red-50 border border-red-200"></div>
                <span class="text-gray-700">Issues: No profit or over estimated hours</span>
              </div>
            </div>
          </div>

          <!-- Search Bar -->
          <div class="relative">
            <input
              v-model="searchQuery"
              type="text"
              placeholder="Search jobs by name, client, or job number..."
              class="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <Search class="absolute left-3 top-3.5 h-4 w-4 text-gray-400" />
          </div>

          <!-- Jobs Grid -->
          <div v-if="loading" class="flex justify-center py-8">
            <div class="text-gray-500">Loading jobs...</div>
          </div>

          <div v-else-if="filteredJobs.length === 0" class="text-center py-8">
            <p class="text-gray-500">No jobs found matching your search.</p>
          </div>

          <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div
              v-for="job in filteredJobs"
              :key="job.job_id"
              class="border rounded-lg shadow-sm hover:shadow-md transition-shadow p-3 relative"
              :class="getJobCardClass(job)"
            >
              <!-- Job Header -->
              <div class="mb-3">
                <div class="flex items-start justify-between mb-1">
                  <h4 class="text-sm font-semibold text-gray-900 truncate pr-4">{{ job.name }}</h4>
                  <span
                    class="text-xs font-medium px-2 py-0.5 rounded bg-gray-100 text-gray-700 flex-shrink-0"
                  >
                    #{{ job.job_number }}
                  </span>
                </div>
                <p class="text-xs text-gray-600 mb-1 truncate">{{ job.client || 'No client' }}</p>

                <!-- Issues Warning -->
                <div v-if="hasJobIssues(job)" class="mt-2">
                  <p class="text-xs text-red-600 font-medium">{{ getJobIssuesText(job) }}</p>
                </div>
              </div>

              <!-- Metrics Grid -->
              <div class="grid grid-cols-3 gap-2 mb-3">
                <!-- Estimated Hours -->
                <div class="text-center">
                  <p class="text-xs text-gray-500 mb-0.5">Est.</p>
                  <p class="text-sm font-semibold text-gray-900">{{ job.estimated_hours }}h</p>
                </div>

                <!-- Actual Hours -->
                <div class="text-center">
                  <p class="text-xs text-gray-500 mb-0.5">Actual</p>
                  <p
                    class="text-sm font-semibold"
                    :class="
                      job.actual_hours > job.estimated_hours ? 'text-red-600' : 'text-gray-900'
                    "
                  >
                    {{ job.actual_hours }}h
                  </p>
                </div>

                <!-- Profit -->
                <div class="text-center">
                  <p class="text-xs text-gray-500 mb-0.5">Profit</p>
                  <p
                    class="text-sm font-semibold"
                    :class="job.profit <= 0 ? 'text-red-600' : 'text-gray-900'"
                  >
                    ${{ formatCurrency(job.profit) }}
                  </p>
                </div>
              </div>

              <!-- Assigned Staff -->
              <div v-if="job.people && job.people.length > 0" class="border-t border-gray-100 pt-2">
                <p class="text-xs text-gray-500 mb-1">Staff:</p>
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="person in job.people"
                    :key="(person as Record<string, string>).id"
                    class="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-700 rounded"
                  >
                    {{ person.name }}
                  </span>
                </div>
              </div>
              <div v-else class="border-t border-gray-100 pt-2">
                <p class="text-xs text-gray-400">No staff assigned</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Search } from 'lucide-vue-next'
import Dialog from '../ui/dialog/Dialog.vue'
import DialogContent from '../ui/dialog/DialogContent.vue'
import DialogHeader from '../ui/dialog/DialogHeader.vue'
import DialogTitle from '../ui/dialog/DialogTitle.vue'
import { schemas } from '../../api/generated/api'
import { api } from '../../api/client'
import { z } from 'zod'
import { formatCurrency } from '../../utils/string-formatting'

type WeeklyJob = z.infer<typeof schemas.WeeklyMetrics>
type WeeklyTimesheetData = z.infer<typeof schemas.WeeklyTimesheetData>

interface Props {
  isOpen: boolean
  weeklyData: WeeklyTimesheetData | null
  weekDate?: string // Week date in YYYY-MM-DD format
}

const props = defineProps<Props>()
const emit = defineEmits<{
  close: []
}>()

const detailedMode = ref(false)
const searchQuery = ref('')
const loading = ref(false)
const isLoading = ref(false)

const jobs = ref<WeeklyJob[]>([])

const filteredJobs = computed<WeeklyJob[]>(() => {
  if (!searchQuery.value.trim()) return jobs.value

  const query = searchQuery.value.toLowerCase()
  return jobs.value.filter(
    (job) =>
      job.name.toLowerCase().includes(query) ||
      (job.client && job.client.toLowerCase().includes(query)) ||
      job.job_number.toString().toLowerCase().includes(query) ||
      (job.description && job.description.toLowerCase().includes(query)),
  )
})

// Computed properties for metrics
const activeJobsCount = computed(() => jobs.value.length)

// Helper functions for job status analysis
const hasJobIssues = (job: WeeklyJob) => {
  return job.profit <= 0 || job.actual_hours > job.estimated_hours
}

const getJobCardClass = (job: WeeklyJob) => {
  const hasNegativeProfit = job.profit <= 0
  const isOverEstimate = job.actual_hours > job.estimated_hours

  if (hasNegativeProfit || isOverEstimate) {
    return 'bg-red-50 border-red-200'
  }
  return 'bg-green-50 border-green-200'
}

const getJobIssuesText = (job: WeeklyJob) => {
  const issues = []
  if (job.profit <= 0) {
    issues.push('No profit')
  }
  if (job.actual_hours > job.estimated_hours) {
    issues.push('Over hours')
  }
  return issues.join(', ')
}

const getProfitComparisonClass = () => {
  if (totalProfit.value >= totalEstimatedProfit.value) {
    return 'bg-green-50 border-green-200'
  }
  return 'bg-red-50 border-red-200'
}

const totalEstimatedProfit = computed(() => {
  return (props.weeklyData?.job_metrics?.total_estimated_profit || 0) as number
})

const totalActualProfit = computed(() => {
  return (props.weeklyData?.job_metrics?.total_actual_profit || 0) as number
})

const totalProfit = computed(() => {
  return (props.weeklyData?.job_metrics?.total_profit || 0) as number
})

const staffCompletionStats = computed(() => {
  if (!props.weeklyData?.staff_data) {
    return { complete: 0, partial: 0, missing: 0 }
  }

  let complete = 0
  let partial = 0
  let missing = 0

  props.weeklyData.staff_data.forEach((staff) => {
    const totalHours = staff.weekly_hours?.reduce((sum, day) => sum + day.hours, 0) || 0

    if (totalHours === 0) {
      missing++
    } else if (totalHours >= 40) {
      complete++
    } else {
      partial++
    }
  })

  return { complete, partial, missing }
})

const closeModal = () => {
  emit('close')
}

const handleOpenChange = (open: boolean) => {
  if (!open) {
    closeModal()
  }
}

const toggleDetailedMode = () => {
  detailedMode.value = !detailedMode.value
  if (detailedMode.value && jobs.value.length === 0) {
    loadJobs()
  }
}

const loadJobs = async () => {
  isLoading.value = true
  try {
    console.log('Props - WEEKLY METRICS MODAL: ', props)
    const response = props.weekDate
      ? await api.job_rest_jobs_weekly_metrics_list({ queries: { week: props.weekDate } })
      : await api.job_rest_jobs_weekly_metrics_list()
    jobs.value = response || []
    console.log(`📊 Loaded ${jobs.value.length} jobs for week: ${props.weekDate || 'current'}`)
  } catch (error) {
    console.error('❌ Error loading jobs:', error)
    toast.error('Failed to load weekly metrics')
    jobs.value = []
  } finally {
    isLoading.value = false
  }
}

// Watch for modal opening to load jobs and metrics
watch(
  () => props.isOpen,
  (isOpen) => {
    if (isOpen) {
      console.log('🔍 Modal opened - weeklyData structure:', {
        weeklyData: props.weeklyData,
        weekDate: props.weekDate,
        job_metrics: props.weeklyData?.job_metrics,
        weekly_summary: props.weeklyData?.weekly_summary,
        weeklyData_keys: props.weeklyData ? Object.keys(props.weeklyData) : 'No weeklyData',
      })

      if (jobs.value.length === 0) {
        loadJobs()
      }
    }
  },
)

// Watch for week date changes to reload jobs
watch(
  () => props.weekDate,
  (newWeekDate, oldWeekDate) => {
    if (props.isOpen && newWeekDate !== oldWeekDate) {
      console.log(`📅 Week changed from ${oldWeekDate} to ${newWeekDate}, reloading jobs...`)
      loadJobs()
    }
  },
)
</script>
