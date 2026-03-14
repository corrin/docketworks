import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { schemas } from '../api/generated/api'
import type { TimesheetEntryWithMeta } from '@/constants/timesheet'
import { z } from 'zod'
import { debugLog } from '@/utils/debug'
import { getJobActualHours, getJobEstimatedHours } from '@/utils/costLineMeta'

type ModernTimesheetJob = z.infer<typeof schemas.ModernTimesheetJob>
type FullJob = z.infer<typeof schemas.Job> | z.infer<typeof schemas.JobSummary>

export function useTimesheetSummary() {
  const router = useRouter()
  const loading = ref(false)
  const error = ref<string | null>(null)

  const getActiveJobs = (jobs: ModernTimesheetJob[]) => {
    return jobs.filter(
      (job) => job.status === 'approved' || job.status === 'in_progress' || job.status === 'draft',
    )
  }

  const getJobHours = (jobId: string, timeEntries: TimesheetEntryWithMeta[]) => {
    const jobEntries = timeEntries.filter((entry) => entry.job_id === jobId)

    debugLog(`getJobHours for jobId ${jobId}:`, {
      jobId,
      totalEntries: timeEntries.length,
      matchingEntries: jobEntries.length,
      allJobIds: timeEntries.map((e) => e.job_id),
      matchingJobIds: jobEntries.map((e) => e.job_id),
      hours: jobEntries.reduce((sum, entry) => sum + (entry.quantity || 0), 0),
    })

    return jobEntries.reduce((sum, entry) => sum + (entry.quantity || 0), 0)
  }

  const getJobBill = (jobId: string, timeEntries: TimesheetEntryWithMeta[]) => {
    const jobEntries = timeEntries.filter((entry) => entry.job_id === jobId)
    return jobEntries.reduce((sum, entry) => sum + (entry.total_rev || 0), 0)
  }

  const getCompletionPercentage = (actualHours: number, estimatedHours: number) => {
    if (estimatedHours <= 0) return 0
    return Math.min((actualHours / estimatedHours) * 100, 100)
  }

  const isJobOverBudget = (actualHours: number, estimatedHours: number) => {
    return estimatedHours > 0 && actualHours > estimatedHours
  }

  const getTotalHours = (timeEntries: TimesheetEntryWithMeta[]) => {
    return timeEntries.reduce((sum, entry) => sum + (entry.quantity || 0), 0)
  }

  const getTotalBill = (timeEntries: TimesheetEntryWithMeta[]) => {
    return timeEntries.reduce((sum, entry) => sum + (entry.total_rev || 0), 0)
  }

  const getBillableFlag = (entry: TimesheetEntryWithMeta): boolean | null => {
    const meta = entry.meta
    if (meta && typeof meta === 'object') {
      const record = meta as Record<string, unknown>
      if (typeof record['is_billable'] === 'boolean') {
        return record['is_billable'] as boolean
      }
    }
    return null
  }

  const getBillableEntries = (timeEntries: TimesheetEntryWithMeta[]) => {
    return timeEntries.filter((entry) => getBillableFlag(entry) === true).length
  }

  const getNonBillableEntries = (timeEntries: TimesheetEntryWithMeta[]) => {
    return timeEntries.filter((entry) => getBillableFlag(entry) === false).length
  }

  const navigateToJob = (jobId: string) => {
    router.push({ name: 'job-edit', params: { id: jobId } })
  }

  const getStatusVariant = (status: string) => {
    switch (status) {
      case 'active':
      case 'in_progress':
        return 'default'
      case 'completed':
        return 'secondary'
      case 'draft':
        return 'outline'
      case 'on_hold':
        return 'destructive'
      default:
        return 'outline'
    }
  }

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'active':
        return 'Active'
      case 'in_progress':
        return 'In Progress'
      case 'completed':
        return 'Completed'
      case 'draft':
        return 'Draft'
      case 'on_hold':
        return 'On Hold'
      default:
        return status
    }
  }

  const getEstimatedHours = (job: FullJob) => {
    debugLog('Received job:', job)
    return getJobEstimatedHours(job)
  }

  const getActualHours = (job: FullJob) => getJobActualHours(job)

  return {
    loading,
    error,
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
    getActualHours,
  }
}
