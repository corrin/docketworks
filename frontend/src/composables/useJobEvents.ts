import { ref, computed } from 'vue'
import type { Ref } from 'vue'
import { schemas } from '../api/generated/api'
import { api } from '../api/client'
import { z } from 'zod'
import { toast } from 'vue-sonner'

type JobEvent = z.infer<typeof schemas.JobEvent>

export function useJobEvents(jobId: string | Ref<string | null>) {
  const loading = ref(false)
  const error = ref<string | null>(null)
  const jobEvents = ref<JobEvent[]>([])

  const getJobId = () => (typeof jobId === 'string' ? jobId : jobId.value)

  async function loadEvents() {
    const id = getJobId()
    if (!id) return

    loading.value = true
    error.value = null

    try {
      const response = await api.job_rest_jobs_events_retrieve({
        params: { job_id: id },
      })
      jobEvents.value = response?.events || []
    } catch (err) {
      error.value = 'Failed to load job events: ' + (err as Error).message
      toast.error('Failed to load job events')
    } finally {
      loading.value = false
    }
  }

  async function addEvent(description: string) {
    const id = getJobId()
    if (!id || !description) return

    loading.value = true
    error.value = null

    try {
      const response = await api.job_rest_jobs_events_create(
        { description },
        { params: { job_id: id } },
      )

      if (response.success && response.event) {
        // Reload events after adding
        await loadEvents()
        toast.success('Event added successfully')
      } else {
        throw new Error('Failed to add event')
      }
    } catch (err: unknown) {
      const e = err as Error
      error.value = e?.message || 'Failed to add event'
      toast.error('Failed to add event')
    } finally {
      loading.value = false
    }
  }

  return {
    jobEvents: computed(() => jobEvents.value),
    loading,
    error,
    addEvent,
  }
}
