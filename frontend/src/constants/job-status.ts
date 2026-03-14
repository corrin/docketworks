/**
 * Job Status Constants
 *
 * These are buggy duplicates of backend logic.
 * They are due to be deleted.  The backend clearly lists job states.
 * These 'statuses' are approximations of those states, and should never have been created
 */

export const JOB_STATUS_CHOICES = [
  { key: 'draft', label: 'Draft', tooltip: 'Initial job creation - quote being prepared' },
  {
    key: 'awaiting_approval',
    label: 'Awaiting Approval',
    tooltip: 'Quote submitted and waiting for customer approval',
  },
  { key: 'approved', label: 'Approved', tooltip: 'Quote approved and ready to start work' },
  { key: 'in_progress', label: 'In Progress', tooltip: 'Work has started on this job' },
  {
    key: 'unusual',
    label: 'Unusual',
    tooltip: 'Jobs requiring special attention - on hold, waiting for materials/staff/site',
  },
  {
    key: 'recently_completed',
    label: 'Recently Completed',
    tooltip: 'Work has just finished on this job (including rejected jobs)',
  },
  {
    key: 'special',
    label: 'Special',
    tooltip: 'Shop jobs, upcoming shutdowns, etc. (not visible on kanban without advanced search)',
  },
  { key: 'archived', label: 'Archived', tooltip: 'The job has been paid for and picked up' },
] as const

export type JobStatusKey = (typeof JOB_STATUS_CHOICES)[number]['key']

export type StatusChoice = {
  key: JobStatusKey
  label: string
  tooltip?: string
}

/**
 * Get status choice by key
 */
export function getStatusChoice(key: JobStatusKey): StatusChoice | undefined {
  return JOB_STATUS_CHOICES.find((choice) => choice.key === key)
}

/**
 * Get status label by key
 */
export function getStatusLabel(key: JobStatusKey): string {
  return getStatusChoice(key)?.label || key
}
