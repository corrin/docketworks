import { ref, computed } from 'vue'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import { safeSessionStorage } from '@/utils/safe-storage'

type WorkshopJob = z.infer<typeof schemas.WorkshopJob>

const STORAGE_KEY = 'activeJobId'

// Singleton pattern - shared state across all consumers
const activeJobId = ref<string | null>(null)
const activeJob = ref<WorkshopJob | null>(null)
const isInitialized = ref(false)

export function useActiveJob() {
  const hasActiveJob = computed(() => !!activeJobId.value && !!activeJob.value)

  // Set active job with full job data
  const setActiveJob = (job: WorkshopJob | null) => {
    if (job) {
      activeJobId.value = job.id
      activeJob.value = job
      safeSessionStorage.set(STORAGE_KEY, job.id)
    } else {
      clearActiveJob()
    }
  }

  // Set just the ID (used when restoring from storage)
  const setActiveJobId = (jobId: string | null) => {
    activeJobId.value = jobId
    if (jobId) {
      safeSessionStorage.set(STORAGE_KEY, jobId)
    } else {
      activeJob.value = null
      safeSessionStorage.remove(STORAGE_KEY)
    }
  }

  // Update job data (when job list is loaded and we can match)
  const updateActiveJobData = (job: WorkshopJob) => {
    if (activeJobId.value === job.id) {
      activeJob.value = job
    }
  }

  // Clear active job
  const clearActiveJob = () => {
    activeJobId.value = null
    activeJob.value = null
    safeSessionStorage.remove(STORAGE_KEY)
  }

  // Initialize from sessionStorage (called once)
  const initializeActiveJob = () => {
    if (isInitialized.value) return

    const stored = safeSessionStorage.get(STORAGE_KEY)
    if (stored) {
      activeJobId.value = stored
      // Note: activeJob data will be populated when jobs list is loaded
    }

    isInitialized.value = true
  }

  // Initialize immediately
  if (!isInitialized.value) {
    initializeActiveJob()
  }

  return {
    activeJobId: computed(() => activeJobId.value),
    activeJob: computed(() => activeJob.value),
    hasActiveJob,
    setActiveJob,
    setActiveJobId,
    updateActiveJobData,
    clearActiveJob,
  }
}
