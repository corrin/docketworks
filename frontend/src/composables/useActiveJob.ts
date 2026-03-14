import { ref, computed } from 'vue'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

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
      try {
        sessionStorage.setItem(STORAGE_KEY, job.id)
      } catch {
        // sessionStorage may be unavailable
      }
    } else {
      clearActiveJob()
    }
  }

  // Set just the ID (used when restoring from storage)
  const setActiveJobId = (jobId: string | null) => {
    activeJobId.value = jobId
    if (jobId) {
      try {
        sessionStorage.setItem(STORAGE_KEY, jobId)
      } catch {
        // sessionStorage may be unavailable
      }
    } else {
      activeJob.value = null
      try {
        sessionStorage.removeItem(STORAGE_KEY)
      } catch {
        // sessionStorage may be unavailable
      }
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
    try {
      sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      // sessionStorage may be unavailable
    }
  }

  // Initialize from sessionStorage (called once)
  const initializeActiveJob = () => {
    if (isInitialized.value) return

    try {
      const stored = sessionStorage.getItem(STORAGE_KEY)
      if (stored) {
        activeJobId.value = stored
        // Note: activeJob data will be populated when jobs list is loaded
      }
    } catch {
      // sessionStorage may be unavailable
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
