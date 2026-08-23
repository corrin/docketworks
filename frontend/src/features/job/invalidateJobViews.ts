import type { QueryClient } from '@tanstack/react-query'

import { getFullJobOptions, jobJobsTimelineRetrieveQueryKey } from '@/api'

/**
 * Mark both server-owned views of one job stale: the job detail the header and
 * every tab read, and the History tab's timeline.
 *
 * The two keys travel together because one write moves both. Every job write
 * the app makes — a header delta PATCH, a manual event, an undo, a cost-line
 * create/update/delete — records a JobEvent or a cost line that
 * `get_job_timeline` merges into the timeline, and each of them also moves
 * something the job detail carries (its fields, its `updated_at` ETag, or a
 * cost set's server-computed summary). Invalidating one key without the other
 * therefore leaves a screen showing what the user just changed alongside a
 * screen that has not heard of it — which is exactly what the History tab did
 * when a header rename invalidated only the job detail.
 *
 * Not awaited by design: callers invalidate after their own mutation has
 * settled, and a refetch of a query nothing has mounted is a no-op, so there
 * is nothing for a caller to wait on. A caller that must await (the field-save
 * hook, whose next edit diffs against the refreshed baseline) awaits the
 * promise this returns.
 */
export function invalidateJobViews(queryClient: QueryClient, jobId: string): Promise<void> {
  const path = { job_id: jobId }
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: getFullJobOptions({ path }).queryKey }),
    queryClient.invalidateQueries({ queryKey: jobJobsTimelineRetrieveQueryKey({ path }) }),
  ]).then(() => undefined)
}
