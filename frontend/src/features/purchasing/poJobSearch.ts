import {
  purchasingAllJobsRetrieve,
  purchasingAllJobsRetrieveQueryKey,
  type JobForPurchasing,
} from '@/api'
import type { JobSearchOptions } from '@/features/shared/JobPicker'

/**
 * The PO grid's background job search: the same endpoint the grid's own list
 * comes from, asked with `q` so it reaches archived jobs the default excludes.
 *
 * No eligibility filter here, unlike the grid's list. jobsBookableOnPoLine
 * drops closed statuses because they are noise in a browse of live work; a
 * user who has typed a closed job's number or name is asking for it by name,
 * and hiding the row they searched for is the worse answer.
 */
export function poJobSearchOptions(term: string): JobSearchOptions<JobForPurchasing> {
  return {
    queryKey: [...purchasingAllJobsRetrieveQueryKey({ query: { q: term } }), 'jobs'],
    queryFn: async ({ signal }) => {
      const { data } = await purchasingAllJobsRetrieve({
        query: { q: term },
        signal,
        throwOnError: true,
      })
      return data.jobs
    },
    enabled: term !== '',
    staleTime: 60_000,
  }
}
