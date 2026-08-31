import { useQuery, useSuspenseQuery } from '@tanstack/react-query'

import { getFullJobOptions, jobJobsCostSetsRetrieveOptions } from '@/api'
import { CostLineGrid } from './CostLineGrid'
import { CostSetSummaryPanel } from './CostSetSummaryPanel'

interface JobEstimateTabProps {
  jobId: string
}

/**
 * Estimate workspace: the editable estimate cost set. Unlike the quote tab
 * this renders for every pricing methodology — a T&M job estimates too, it
 * just never pushes a quote. The grid is the same one component; only the
 * cost-set kind differs.
 */
export function JobEstimateTab({ jobId }: JobEstimateTabProps) {
  // Cache hit: JobDetailPage already holds this query; company defaults ride
  // beside the job in its payload.
  const fullJob = useSuspenseQuery(getFullJobOptions({ path: { job_id: jobId } }))
  const companyDefaults = fullJob.data.data.company_defaults
  // A second subscription to the query the grid owns — a cache share, not a
  // second fetch, so the summary tracks every settled write.
  const costSetQuery = useQuery(
    jobJobsCostSetsRetrieveOptions({ path: { job_id: jobId, kind: 'estimate' } }),
  )

  return (
    <div className="space-y-4 p-6">
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1fr_320px]">
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="text-lg font-semibold text-gray-900">Estimate Details</h2>
          <div className="mt-3">
            <CostLineGrid
              jobId={jobId}
              kind="estimate"
              materialsMarkup={String(companyDefaults.materials_markup)}
              wageRate={String(companyDefaults.wage_rate)}
            />
          </div>
        </section>

        <div className="space-y-4 lg:sticky lg:top-4">
          <CostSetSummaryPanel
            title="Estimate Summary"
            automationId="JobEstimateTab-summary"
            summary={costSetQuery.data?.summary}
            isError={costSetQuery.isError}
          />
        </div>
      </div>
    </div>
  )
}
