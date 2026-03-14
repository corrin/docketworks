<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { useActiveJob } from '@/composables/useActiveJob'
import ActiveJobCard from '@/components/board/ActiveJobCard.vue'
import NoActiveJobPrompt from '@/components/board/NoActiveJobPrompt.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardHeader, CardTitle, CardContent, CardAction } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerOverlay,
  DrawerTitle,
} from '@/components/ui/drawer'
import { toast } from 'vue-sonner'
import { debugLog } from '@/utils/debug'
import type { z } from 'zod'

type WorkshopJob = z.infer<typeof schemas.WorkshopJob>

const router = useRouter()
const { activeJobId, activeJob, hasActiveJob, setActiveJob, updateActiveJobData, clearActiveJob } =
  useActiveJob()

const jobs = ref<WorkshopJob[]>([])
const loading = ref(false)
const showJobPicker = ref(false)
const jobSearch = ref('')

// Filter jobs for the picker based on search
const filteredJobs = computed(() => {
  if (!jobSearch.value.trim()) {
    return jobs.value
  }
  const search = jobSearch.value.toLowerCase()
  return jobs.value.filter(
    (job) =>
      job.name.toLowerCase().includes(search) ||
      job.client_name.toLowerCase().includes(search) ||
      String(job.job_number).includes(search),
  )
})

// Load jobs from API
const loadJobs = async () => {
  loading.value = true
  try {
    jobs.value = await api.job_api_jobs_workshop_list()
    // If we have an activeJobId from storage, find and update the full job data
    if (activeJobId.value) {
      const foundJob = jobs.value.find((j) => j.id === activeJobId.value)
      if (foundJob) {
        updateActiveJobData(foundJob)
      } else {
        // Job no longer in the list, clear the selection
        clearActiveJob()
      }
    }
  } catch (error) {
    debugLog('Error loading workshop jobs:', error)
    toast.error('Failed to load jobs. Please try again.')
  } finally {
    loading.value = false
  }
}

// Handle job selection from picker
const handleJobSelect = (jobId: string) => {
  const job = jobs.value.find((j) => j.id === jobId)
  if (job) {
    setActiveJob(job)
  }
  showJobPicker.value = false
  jobSearch.value = ''
}

// Navigate to job details
const navigateToJob = () => {
  if (activeJob.value) {
    router.push(`/jobs/${activeJob.value.id}/workshop`)
  }
}

// Open job picker
const openJobPicker = () => {
  showJobPicker.value = true
}

onMounted(() => {
  loadJobs()
})

// Re-check active job when jobs list changes
watch(jobs, (newJobs) => {
  if (activeJobId.value && newJobs.length > 0) {
    const foundJob = newJobs.find((j) => j.id === activeJobId.value)
    if (foundJob) {
      updateActiveJobData(foundJob)
    }
  }
})
</script>

<template>
  <div class="workshop-mode-container p-4 max-w-4xl mx-auto">
    <!-- Loading State -->
    <div v-if="loading" class="space-y-4">
      <Card class="max-w-2xl mx-auto">
        <CardHeader>
          <CardTitle>
            <Skeleton class="h-6 w-32" />
          </CardTitle>
          <CardAction>
            <Skeleton class="h-8 w-24" />
          </CardAction>
        </CardHeader>
        <CardContent class="space-y-3">
          <Skeleton class="h-5 w-full" />
          <Skeleton class="h-5 w-3/4" />
          <Skeleton class="h-5 w-1/2" />
          <Skeleton class="h-10 w-full mt-4" />
        </CardContent>
      </Card>
    </div>

    <!-- Active Job Display -->
    <div v-else-if="hasActiveJob && activeJob" class="active-job-section">
      <ActiveJobCard :job="activeJob" @change-job="openJobPicker" @view-job="navigateToJob" />
    </div>

    <!-- No Active Job Prompt -->
    <div v-else class="no-job-prompt">
      <NoActiveJobPrompt @select-job="openJobPicker" />
    </div>

    <!-- Job Picker Drawer -->
    <Drawer :open="showJobPicker" @update:open="showJobPicker = $event">
      <DrawerOverlay />
      <DrawerContent
        class="flex !h-[90vh] !max-h-[90vh] min-h-0 flex-col overflow-hidden sm:!h-auto sm:!max-h-[85vh]"
      >
        <div class="mx-auto flex h-full w-full max-w-4xl flex-col min-h-0">
          <DrawerHeader>
            <DrawerTitle class="text-xl font-semibold">Select a job</DrawerTitle>
            <DrawerDescription>Search by job number, name, or client</DrawerDescription>
          </DrawerHeader>
          <div class="flex-1 overflow-y-auto px-4 pb-4 space-y-3">
            <input
              v-model="jobSearch"
              type="text"
              placeholder="Search jobs..."
              class="w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <div class="overflow-x-auto rounded-md border">
              <table class="min-w-full text-sm">
                <thead class="bg-muted sticky top-0">
                  <tr>
                    <th class="text-left px-3 py-2 font-semibold">Job #</th>
                    <th class="text-left px-3 py-2 font-semibold">Name</th>
                    <th class="text-left px-3 py-2 font-semibold">Client</th>
                    <th class="text-left px-3 py-2 font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="job in filteredJobs" :key="job.id" class="border-t hover:bg-muted/50">
                    <td class="px-3 py-2 whitespace-nowrap">#{{ job.job_number }}</td>
                    <td class="px-3 py-2">{{ job.name }}</td>
                    <td class="px-3 py-2">{{ job.client_name || '-' }}</td>
                    <td class="px-3 py-2">
                      <Button size="sm" class="h-8 px-3" @click="handleJobSelect(job.id)">
                        Select
                      </Button>
                    </td>
                  </tr>
                  <tr v-if="filteredJobs.length === 0">
                    <td colspan="4" class="px-3 py-4 text-center text-muted-foreground">
                      No jobs found.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <DrawerFooter class="px-4 pb-4">
            <DrawerClose as-child>
              <Button variant="outline" size="sm">Close</Button>
            </DrawerClose>
          </DrawerFooter>
        </div>
      </DrawerContent>
    </Drawer>
  </div>
</template>
