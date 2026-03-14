/**
 * Purely visual navigation configuration for job tabs.
 */

import { z } from 'zod'

export const JobTabsSchema = z.enum([
  'estimate',
  'quote',
  'actual',
  'financial',
  'costAnalysis',
  'jobSettings',
  'history',
  'attachments',
  'quotingChat',
  'safety',
])

export type JobTabKey = z.infer<typeof JobTabsSchema>
