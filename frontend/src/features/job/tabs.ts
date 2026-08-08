export const JOB_TAB_KEYS = [
  'estimate',
  'quote',
  'actual',
  'finishJob',
  'jobSettings',
  'history',
  'attachments',
  'quotingChat',
  'safety',
] as const

export type JobTabKey = (typeof JOB_TAB_KEYS)[number]

export const TAB_LABELS: Record<JobTabKey, string> = {
  estimate: 'Estimate',
  quote: 'Quote',
  actual: 'Actual',
  finishJob: 'Finish Job',
  jobSettings: 'Job Settings',
  history: 'History',
  attachments: 'Attachments',
  quotingChat: 'Quoting Chat',
  safety: 'Safety',
}

export function isJobTabKey(value: string): value is JobTabKey {
  return (JOB_TAB_KEYS as readonly string[]).includes(value)
}
