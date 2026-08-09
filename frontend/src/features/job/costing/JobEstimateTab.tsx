import { useSuspenseQuery } from '@tanstack/react-query'

import { getFullJobOptions } from '@/api'
import { CostLineGrid } from './CostLineGrid'

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

  return (
    <div className="space-y-4 p-6">
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
    </div>
  )
}
