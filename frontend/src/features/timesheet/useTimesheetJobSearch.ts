import { useQuery } from '@tanstack/react-query'

import { timesheetsJobsRetrieveOptions, type TimesheetJobOut } from '@/api'
import type { BackgroundJobSearch } from '@/features/shared/JobPicker'

/**
 * The timesheet grid's background job search: the same endpoint the grid's own
 * list comes from, asked with `q` so it reaches the whole table instead of the
 * active set. The rows come back in the SAME shape, so a picked archived job
 * carries its labour rates and prices a draft without a second fetch.
 *
 * The picker supplies an already-debounced term, blank whenever it must not
 * spend a request — so `enabled` is the only gate needed here.
 */
export function useTimesheetJobSearch(term: string): BackgroundJobSearch<TimesheetJobOut> {
  const query = useQuery({
    ...timesheetsJobsRetrieveOptions({ query: { q: term } }),
    enabled: term !== '',
    // A term's results do not change under the user mid-pick, and reopening
    // the picker on the same term should not re-hit the wire.
    staleTime: 60_000,
  })

  return {
    jobs: query.data?.jobs ?? [],
    isFetching: query.isFetching,
    isError: query.isError,
  }
}
