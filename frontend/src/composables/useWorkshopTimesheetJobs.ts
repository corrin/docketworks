import { computed, ref } from 'vue'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { toast } from 'vue-sonner'
import type { z } from 'zod'

type JobsListResponse = z.infer<typeof schemas.JobsListResponse>

export function useWorkshopTimesheetJobs() {
  const jobs = ref<JobsListResponse['jobs']>([])
  const jobSearch = ref('')

  const filteredJobs = computed(() => {
    const term = jobSearch.value.trim().toLowerCase()
    if (!term) return jobs.value
    return jobs.value.filter((job) => {
      const number = String(job.job_number).toLowerCase()
      const name = (job.name || '').toLowerCase()
      const client = (job.client_name || '').toLowerCase()
      return number.includes(term) || name.includes(term) || client.includes(term)
    })
  })

  async function loadJobs() {
    try {
      const response = await api.timesheets_api_jobs_retrieve()
      jobs.value = response.jobs || []
    } catch (error) {
      console.error('Failed to load jobs for timesheets', error)
      toast.error('Could not load jobs list.')
    }
  }

  return {
    jobs,
    jobSearch,
    filteredJobs,
    loadJobs,
  }
}
