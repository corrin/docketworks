import { useQuery } from '@tanstack/react-query'

import { purchasingAllJobsRetrieveOptions, type JobForPurchasing } from '@/api'
import type { BackgroundJobSearch } from '@/features/shared/JobPicker'

/**
 * The PO grid's background job search: the same endpoint the grid's own list
 * comes from, asked with `q` so it reaches archived jobs the default excludes.
 *
 * No eligibility filter here, unlike the grid's list. jobsBookableOnPoLine
 * drops closed statuses because they are noise in a browse of live work; a
 * user who has typed a closed job's number or name is asking for it by name,
 * and hiding the row they searched for is the worse answer.
 */
export function usePoJobSearch(term: string): BackgroundJobSearch<JobForPurchasing> {
  const query = useQuery({
    ...purchasingAllJobsRetrieveOptions({ query: { q: term } }),
    enabled: term !== '',
    staleTime: 60_000,
  })

  return {
    jobs: query.data?.jobs ?? [],
    isFetching: query.isFetching,
    isError: query.isError,
  }
}
