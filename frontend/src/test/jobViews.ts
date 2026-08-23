import type { QueryClient, QueryKey } from '@tanstack/react-query'

import { getFullJobOptions, jobJobsTimelineRetrieveQueryKey } from '@/api'

export interface JobViewKeys {
  job: QueryKey
  timeline: QueryKey
}

/**
 * Seed one job's view keys with a marker and hand back both keys, so a test
 * can assert that a write invalidated them (invalidateJobViews).
 *
 * `views` names which of them to seed, and defaults to both. A view the
 * screen under test reads itself must be left out: its own query owns that
 * cache entry, so seeding it would replace the rendered data with the marker,
 * and its invalidation is visible as a refetch rather than as a lasting
 * `isInvalidated` — an observed query clears the flag as soon as the refetch
 * lands.
 *
 * The keys are widened to QueryKey rather than cast: the generated keys carry
 * a payload tag, and the assertions are about which cache entries were
 * invalidated, not about the payload shape — a whole JobDetailResponse here
 * would be fixture noise with nothing reading it.
 */
export function seedJobViews(
  queryClient: QueryClient,
  jobId: string,
  views: readonly (keyof JobViewKeys)[] = ['job', 'timeline'],
): JobViewKeys {
  const path = { job_id: jobId }
  const keys: JobViewKeys = {
    job: getFullJobOptions({ path }).queryKey,
    timeline: jobJobsTimelineRetrieveQueryKey({ path }),
  }
  // gcTime, because renderWithProviders' client sets gcTime: 0 and these two
  // queries have no observer on the screen under test: without it the cache
  // entry is evicted the moment it is written and getQueryState reads
  // undefined, which is indistinguishable from "never invalidated".
  for (const view of views) {
    const key = keys[view]
    queryClient.setQueryDefaults(key, { gcTime: Infinity })
    queryClient.setQueryData(key, { seeded: true })
  }
  return keys
}
