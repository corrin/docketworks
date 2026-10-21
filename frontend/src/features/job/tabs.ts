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

export function isJobTabKey(value: string): value is JobTabKey {
  return (JOB_TAB_KEYS as readonly string[]).includes(value)
}
