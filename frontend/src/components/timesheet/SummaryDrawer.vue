<template>
  <Drawer :open="isOpen" @update:open="isOpen = $event">
    <DrawerContent class="max-h-[85vh]">
      <div class="mx-auto w-full max-w-4xl">
        <DrawerHeader>
          <DrawerTitle class="text-xl font-semibold">Timesheet Summary</DrawerTitle>
          <DrawerDescription> Overview of active jobs and timesheet entries </DrawerDescription>
        </DrawerHeader>

        <div class="px-4 pb-4 overflow-y-auto max-h-[calc(85vh-120px)]">
          <!-- Loading State -->
          <div v-if="loading" class="flex items-center justify-center py-8">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-600 mb-2"></div>
            <span class="text-gray-600 text-sm ml-2">Loading summary...</span>
          </div>

          <!-- Error State -->
          <div v-else-if="error" class="flex items-center justify-center py-8">
            <div class="text-center">
              <AlertTriangle class="h-8 w-8 text-red-500 mx-auto mb-2" />
              <p class="text-red-600 text-sm">{{ error }}</p>
            </div>
          </div>

          <!-- Content -->
          <div v-else class="space-y-6">
            <!-- Consolidated Summary -->
            <div class="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
              <Card class="p-3 md:p-4">
                <div class="flex items-center space-x-2">
                  <Clock class="h-4 w-4 text-blue-600 flex-shrink-0" />
                  <div class="min-w-0">
                    <p class="text-xs md:text-sm text-gray-600">Total Hours</p>
                    <p class="text-base md:text-lg font-semibold">
                      {{ formatHoursDisplay(consolidatedSummary.totalHours) }}
                    </p>
                  </div>
                </div>
              </Card>

              <Card class="p-3 md:p-4">
                <div class="flex items-center space-x-2">
                  <DollarSign class="h-4 w-4 text-green-600 flex-shrink-0" />
                  <div class="min-w-0">
                    <p class="text-xs md:text-sm text-gray-600">Total Bill</p>
                    <p class="text-base md:text-lg font-semibold">
                      {{ formatCurrency(consolidatedSummary.totalBill) }}
                    </p>
                  </div>
                </div>
              </Card>

              <Card class="p-3 md:p-4">
                <div class="flex items-center space-x-2">
                  <CheckCircle class="h-4 w-4 text-green-600 flex-shrink-0" />
                  <div class="min-w-0">
                    <p class="text-xs md:text-sm text-gray-600">Billable</p>
                    <p class="text-base md:text-lg font-semibold">
                      {{ consolidatedSummary.billableEntries }}
                    </p>
                  </div>
                </div>
              </Card>

              <Card class="p-3 md:p-4">
                <div class="flex items-center space-x-2">
                  <XCircle class="h-4 w-4 text-gray-600 flex-shrink-0" />
                  <div class="min-w-0">
                    <p class="text-xs md:text-sm text-gray-600">Non-Billable</p>
                    <p class="text-base md:text-lg font-semibold">
                      {{ consolidatedSummary.nonBillableEntries }}
                    </p>
                  </div>
                </div>
              </Card>
            </div>

            <!-- Active Jobs Cards -->
            <div>
              <h3 class="text-lg font-semibold mb-4">Active Jobs</h3>

              <div v-if="activeJobsWithData.length === 0" class="text-center py-8">
                <p class="text-gray-500">No active jobs with timesheet entries found</p>
              </div>

              <div
                v-else
                class="grid grid-cols-1 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
              >
                <Card
                  v-for="jobData in activeJobsWithData"
                  :key="jobData.job.id"
                  class="p-3 md:p-4 hover:shadow-md transition-shadow cursor-pointer"
                  @click="navigateToJob(jobData.job.id)"
                >
                  <div class="space-y-3">
                    <!-- Job Header -->
                    <div class="flex items-start justify-between">
                      <div class="flex-1">
                        <h4
                          class="font-semibold text-blue-600 hover:text-blue-800 transition-colors"
                        >
                          Job {{ jobData.job.job_number }}
                        </h4>
                        <p class="text-sm text-gray-600 truncate">{{ jobData.job.name }}</p>
                        <p class="text-xs text-gray-500 truncate">{{ jobData.job.client_name }}</p>
                      </div>
                      <!-- TODO: Backend inconsistency - Job uses 'job_status', ModernTimesheetJob uses 'status'.
                           jobData.job is FullJob | ModernTimesheetJob union due to enhancedJob || job fallback.
                           Backend should normalize to single field name. -->
                      <Badge
                        :variant="
                          getStatusVariant(
                            (jobData.job as any).job_status || (jobData.job as any).status,
                          )
                        "
                      >
                        {{
                          getStatusLabel(
                            (jobData.job as any).job_status || (jobData.job as any).status,
                          )
                        }}
                      </Badge>
                    </div>

                    <!-- Hours Progress -->
                    <div class="space-y-2">
                      <div class="flex justify-between text-sm">
                        <span class="text-gray-600">Hours Progress</span>
                        <span class="font-medium">
                          {{ formatHoursDisplay(jobData.actualHours) }} /
                          {{ formatHoursDisplay(jobData.estimatedHours) }}
                        </span>
                      </div>

                      <div class="w-full bg-gray-200 rounded-full h-2">
                        <div
                          class="h-2 rounded-full transition-all duration-300"
                          :class="jobData.isOverBudget ? 'bg-red-500' : 'bg-blue-500'"
                          :style="{ width: `${Math.min(jobData.completionPercentage, 100)}%` }"
                        ></div>
                      </div>

                      <div class="flex justify-between text-xs">
                        <span :class="jobData.isOverBudget ? 'text-red-600' : 'text-gray-600'">
                          {{ jobData.completionPercentage.toFixed(1) }}% complete
                        </span>
                        <span v-if="jobData.isOverBudget" class="text-red-600 font-medium">
                          Over Budget
                        </span>
                      </div>
                    </div>

                    <!-- Financial Info -->
                    <div class="flex justify-between items-center pt-2 border-t border-gray-100">
                      <div class="text-sm">
                        <span class="text-gray-600">Total Bill:</span>
                        <span class="font-semibold ml-1">{{
                          formatCurrency(jobData.totalBill)
                        }}</span>
                      </div>
                      <ExternalLink class="h-4 w-4 text-gray-400" />
                    </div>
                  </div>
                </Card>
              </div>
            </div>
          </div>
        </div>

        <DrawerFooter>
          <DrawerClose as-child>
            <Button variant="outline">Close</Button>
          </DrawerClose>
        </DrawerFooter>
      </div>
    </DrawerContent>
  </Drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  Clock,
  DollarSign,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ExternalLink,
} from 'lucide-vue-next'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer'

import { useTimesheetSummary } from '@/composables/useTimesheetSummary'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import type { TimesheetEntryWithMeta } from '@/constants/timesheet'
import { debugLog } from '../../utils/debug'
import { z } from 'zod'
import { formatCurrency, formatHoursDisplay } from '@/utils/string-formatting'

type ModernTimesheetJob = z.infer<typeof schemas.ModernTimesheetJob>
type FullJob = z.infer<typeof schemas.Job> | z.infer<typeof schemas.JobSummary>

interface Props {
  open: boolean
  jobs: ModernTimesheetJob[]
  timeEntries: TimesheetEntryWithMeta[]
  loading?: boolean
  error?: string | null
}

interface Emits {
  'update:open': [value: boolean]
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  error: null,
})

const emit = defineEmits<Emits>()

const {
  getActiveJobs,
  getJobHours,
  getJobBill,
  getCompletionPercentage,
  isJobOverBudget,
  getTotalHours,
  getTotalBill,
  getBillableEntries,
  getNonBillableEntries,
  navigateToJob,
  getStatusVariant,
  getStatusLabel,
  getEstimatedHours,
} = useTimesheetSummary()

// State for enhanced job details
const enhancedJobs = ref<Map<string, FullJob>>(new Map())
const loadingJobDetails = ref(false)

// Get unique job IDs from timesheet entries
const jobIdsWithEntries = computed(() => {
  const jobIds = new Set<string>()
  props.timeEntries.forEach((entry) => {
    if (entry.job_id) {
      jobIds.add(entry.job_id)
    }
  })
  return Array.from(jobIds)
})

// Load full job details for jobs that have timesheet entries
const loadJobDetails = async () => {
  if (jobIdsWithEntries.value.length === 0) return

  loadingJobDetails.value = true
  debugLog('Loading job details for jobs with entries:', jobIdsWithEntries.value)

  try {
    const jobPromises = jobIdsWithEntries.value.map(async (jobId) => {
      try {
        const jobDetail = await api.getJobSummary({ params: { job_id: jobId } })
        debugLog('Job detail: ', jobDetail)
        return { jobId, job: jobDetail.data.job }
      } catch (err) {
        debugLog('Failed to load job details for:', jobId, err)
        return null
      }
    })

    const results = await Promise.all(jobPromises)
    const newEnhancedJobs = new Map<string, FullJob>()

    results.forEach((result) => {
      if (result) {
        newEnhancedJobs.set(result.jobId, result.job)
      }
    })

    enhancedJobs.value = newEnhancedJobs
    debugLog('Loaded enhanced job details:', enhancedJobs.value.size)
  } catch (err) {
    debugLog('Error loading job details:', err)
  } finally {
    loadingJobDetails.value = false
  }
}

// Watch for changes in job IDs with entries and load details
watch(
  () => jobIdsWithEntries.value,
  (newJobIds) => {
    if (newJobIds.length > 0 && props.open) {
      loadJobDetails()
    }
  },
  { immediate: false },
)

// Load job details when drawer opens
watch(
  () => props.open,
  (isOpen) => {
    if (isOpen && jobIdsWithEntries.value.length > 0) {
      loadJobDetails()
    }
  },
)

// Computed properties
const activeJobs = computed(() => {
  debugLog('SummaryDrawer - Computing active jobs:', {
    totalJobs: props.jobs.length,
    jobs: props.jobs
      .slice(0, 3)
      .map((j) => ({ id: j.id, job_number: j.job_number, status: j.status })),
  })
  const active = getActiveJobs(props.jobs)
  debugLog('SummaryDrawer - Active jobs result:', {
    activeJobsCount: active.length,
    activeJobs: active
      .slice(0, 3)
      .map((j) => ({ id: j.id, job_number: j.job_number, status: j.status })),
  })
  return active
})

const consolidatedSummary = computed(() => ({
  totalHours: getTotalHours(props.timeEntries),
  totalBill: getTotalBill(props.timeEntries),
  billableEntries: getBillableEntries(props.timeEntries),
  nonBillableEntries: getNonBillableEntries(props.timeEntries),
  activeJobs: activeJobs.value.length,
}))

const activeJobsWithData = computed(() => {
  debugLog('SummaryDrawer - Computing jobs with data:', {
    activeJobsCount: activeJobs.value.length,
    timeEntriesCount: props.timeEntries.length,
    enhancedJobsCount: enhancedJobs.value.size,
    timeEntries: props.timeEntries
      .slice(0, 3)
      .map((e) => ({ id: e.id, job_id: e.job_id, quantity: e.quantity })),
  })

  const jobsWithData = activeJobs.value
    .map((job) => {
      const actualHours = getJobHours(job.id, props.timeEntries)

      // Skip jobs without timesheet entries
      if (actualHours === 0) return null

      // Use enhanced job data if available, otherwise use basic job data
      const enhancedJob = enhancedJobs.value.get(job.id)

      const estimatedHours = enhancedJob ? getEstimatedHours(enhancedJob) : 0
      const totalBill = getJobBill(job.id, props.timeEntries)
      const completionPercentage = getCompletionPercentage(actualHours, estimatedHours)
      const isOverBudget = isJobOverBudget(actualHours, estimatedHours)

      debugLog(`Job ${job.job_number} data:`, {
        jobId: job.id,
        actualHours,
        estimatedHours,
        totalBill,
        hasEnhancedData: !!enhancedJob,
        matchingEntries: props.timeEntries.filter((e) => e.job_id === job.id).length,
      })

      return {
        job: enhancedJob || job, // Use enhanced job if available
        actualHours,
        estimatedHours,
        totalBill,
        completionPercentage,
        isOverBudget,
      }
    })
    .filter((jobData) => jobData !== null) // Remove null entries
    .sort((a, b) => b.actualHours - a.actualHours) // Sort by hours worked (descending)

  debugLog('SummaryDrawer - Final jobs with data:', {
    filteredJobsCount: jobsWithData.length,
    jobs: jobsWithData.map((jd) => ({
      job_number: jd.job.job_number,
      actualHours: jd.actualHours,
    })),
  })

  return jobsWithData
})

// Update open prop
const isOpen = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})
</script>
