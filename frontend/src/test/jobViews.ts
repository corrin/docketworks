import type { QueryClient, QueryKey } from '@tanstack/react-query'

import { getFullJobOptions, jobJobsTimelineRetrieveQueryKey } from '@/api'

export interface JobViewKeys {
  job: QueryKey
  timeline: QueryKey
}

/**
 * Seed one job's two view keys with a marker and hand back the keys, so a test
 * can assert that a write invalidated both (invalidateJobViews).
 *
 * The keys are widened to QueryKey rather than cast: the generated keys carry
 * a payload tag, and the assertions are about which cache entries were
 * invalidated, not about the payload shape — a whole JobDetailResponse here
 * would be fixture noise with nothing reading it.
 */
export function seedJobViews(queryClient: QueryClient, jobId: string): JobViewKeys {
  const path = { job_id: jobId }
  const keys: JobViewKeys = {
    job: getFullJobOptions({ path }).queryKey,
    timeline: jobJobsTimelineRetrieveQueryKey({ path }),
  }
  // gcTime, because renderWithProviders' client sets gcTime: 0 and these two
  // queries have no observer on the screen under test: without it the cache
  // entry is evicted the moment it is written and getQueryState reads
  // undefined, which is indistinguishable from "never invalidated".
  for (const key of [keys.job, keys.timeline]) {
    queryClient.setQueryDefaults(key, { gcTime: Infinity })
    queryClient.setQueryData(key, { seeded: true })
  }
  return keys
}
