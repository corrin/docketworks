import { timesheetsJobsRetrieve, timesheetsJobsRetrieveQueryKey, type TimesheetJobOut } from '@/api'
import type { JobSearchOptions } from '@/features/shared/JobPicker'

/**
 * The timesheet grid's background job search: the same endpoint the grid's own
 * list comes from, asked with `q` so it reaches the whole table instead of the
 * active set. The rows come back in the SAME shape, so a picked archived job
 * carries its labour rates and prices a draft without a second fetch.
 *
 * The picker supplies an already-debounced term, blank whenever it must not
 * spend a request — so `enabled` is the only gate needed here.
 */
export function timesheetJobSearchOptions(term: string): JobSearchOptions<TimesheetJobOut> {
  return {
    queryKey: [...timesheetsJobsRetrieveQueryKey({ query: { q: term } }), 'jobs'],
    queryFn: async ({ signal }) => {
      const { data } = await timesheetsJobsRetrieve({
        query: { q: term },
        signal,
        throwOnError: true,
      })
      return data.jobs
    },
    enabled: term !== '',
    // A term's results do not change under the user mid-pick, and reopening
    // the picker on the same term should not re-hit the wire.
    staleTime: 60_000,
  }
}
