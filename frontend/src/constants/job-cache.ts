/**
 * Job Cache Constants
 *
 * Exclusive cache structure (data + timestamp + version) for job details.
 * This defines the shape of job cache data for frontend caching, something that's purely UI-related.
 */

import { z } from 'zod'
import { schemas } from '@/api/generated/api'

/**
 * Schema for job cache entry
 */
export const JobCacheEntrySchema = z.object({
  data: schemas.JobDetailResponse,
  timestamp: z.date(),
  version: z.number(),
})

export type JobCacheEntry = z.infer<typeof JobCacheEntrySchema>
