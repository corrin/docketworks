import type { QueryClient } from '@tanstack/react-query'

import { getFullJobOptions, jobJobsTimelineRetrieveQueryKey } from '@/api'

/**
 * Mark both server-owned views of one job stale: the job detail, and the
 * History tab's timeline.
 *
 * The two keys travel together because the writes that move one move the
 * other. A write lands on the timeline when it records a JobEvent or a cost
 * line, which `get_job_timeline` merges; it lands on the job detail because
 * the job's ETag is derived from its `updated_at`
 * (`generate_updated_at_etag` in apps/job/api.py), and a getFullJob response
 * is the only thing that re-arms the etag store the header's If-Match reads
 * (src/lib/concurrency/interceptors.ts). A write that bumps `updated_at`
 * without refreshing that store leaves the user's next header edit to 412.
 *
 * One writer is NOT covered: `features/timesheet/useTimesheetEntries.ts`
 * writes cost lines against arbitrary jobs and would have to reach across
 * features to call this. The hole is real — open a job, book time to it on
 * Timesheets, come back inside the 30s staleTime, and the next header edit
 * 412s. Its fix is server-side and deferred: see the cost-line
 * `_set_job_etag` row in docs/rewrite-status.md.
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
