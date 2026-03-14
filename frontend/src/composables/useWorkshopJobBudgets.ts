import { computed, ref, type ComputedRef } from 'vue'
import { schemas } from '@/api/generated/api'
import { jobService } from '@/services/job.service'
import { useTimesheetSummary } from '@/composables/useTimesheetSummary'
import { formatHoursValue } from '@/composables/useWorkshopTimesheetTimeUtils'
import type { z } from 'zod'

type Job = z.infer<typeof schemas.Job>
type JobSummary = z.infer<typeof schemas.JobSummary>

export type JobBudgetMeta = {
  job: Job | JobSummary
  estimatedHours: number
  actualHours: number
  overBudget: boolean
}

export function useWorkshopJobBudgets(selectedJobIds: ComputedRef<string[]>) {
  const jobBudgetMeta = ref<Map<string, JobBudgetMeta>>(new Map())
  const { getEstimatedHours, getActualHours } = useTimesheetSummary()

  const selectedDayBudgetMeta = computed(() =>
    selectedJobIds.value
      .map((jobId) => {
        const meta = jobBudgetMeta.value.get(jobId)
        if (!meta) return null
        return { jobId, ...meta }
      })
      .filter((meta): meta is { jobId: string } & JobBudgetMeta => meta !== null),
  )
  const overBudgetJobs = computed(() =>
    selectedDayBudgetMeta.value.filter((meta) => meta.overBudget),
  )
  const overBudgetTooltip = computed(() => {
    if (overBudgetJobs.value.length === 0) return ''

    return overBudgetJobs.value
      .map(
        (meta) =>
          `#${meta.job.job_number} ${meta.job.name}: ${formatHoursValue(meta.actualHours)} / ${formatHoursValue(meta.estimatedHours)}`,
      )
      .join('\n')
  })

  async function refreshJobBudgets(jobIds: string[]): Promise<void> {
    if (!jobIds || jobIds.length === 0) {
      jobBudgetMeta.value = new Map()
      return
    }

    try {
      const results = await Promise.all(
        jobIds.map(async (jobId) => {
          try {
            const response = await jobService.getJobSummary(jobId)
            const job = response.data.job
            const estimatedHours = Math.max(0, getEstimatedHours(job) || 0)
            const actualHours = Math.max(0, getActualHours(job) || 0)
            return {
              jobId,
              meta: {
                job,
                estimatedHours,
                actualHours,
                overBudget: estimatedHours > 0 && actualHours > estimatedHours,
              },
            }
          } catch (error) {
            console.error('Failed to load job hours for workshop timesheets', error)
            return { jobId, meta: null }
          }
        }),
      )

      const next = new Map<string, JobBudgetMeta>()
      results.forEach(({ jobId, meta }) => {
        if (meta) {
          next.set(jobId, meta)
        } else {
          const existing = jobBudgetMeta.value.get(jobId)
          if (existing) next.set(jobId, existing)
        }
      })

      jobBudgetMeta.value = next
    } catch (error) {
      console.error('Failed to refresh job budget data', error)
    }
  }

  function getJobBudgetState(jobId?: string | null): JobBudgetMeta | null {
    if (!jobId) return null
    return jobBudgetMeta.value.get(jobId) ?? null
  }

  return {
    jobBudgetMeta,
    selectedDayBudgetMeta,
    overBudgetJobs,
    overBudgetTooltip,
    refreshJobBudgets,
    getJobBudgetState,
  }
}
