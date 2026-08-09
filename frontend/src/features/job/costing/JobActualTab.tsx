import { useQuery, useSuspenseQuery } from '@tanstack/react-query'

import { getFullJobOptions, jobJobsCostSetsRetrieveOptions } from '@/api'
import { formatCurrency } from '@/lib/format'
import { CostLineGrid } from './CostLineGrid'

interface JobActualTabProps {
  jobId: string
}

/**
 * Actual costs workspace: the job's actual cost set in the one grid.
 * Timesheet labour arrives as read-only time lines (booked in the timesheet
 * UI), materials are booked by consuming stock, and free-typed rows become
 * adjustments. The Time & Expenses chip renders the server-owned summary
 * revenue verbatim (ADR 0046) — invoice figures deliberately live in Finish
 * Job only.
 */
export function JobActualTab({ jobId }: JobActualTabProps) {
  // Cache hit: JobDetailPage already holds this query; company defaults ride
  // beside the job in its payload.
  const fullJob = useSuspenseQuery(getFullJobOptions({ path: { job_id: jobId } }))
  const companyDefaults = fullJob.data.data.company_defaults
  // A second subscription to the query the grid owns — a cache share, not a
  // second fetch, so the chip tracks every settled write.
  const costSetQuery = useQuery(
    jobJobsCostSetsRetrieveOptions({ path: { job_id: jobId, kind: 'actual' } }),
  )
  const summary = costSetQuery.data?.summary

  return (
    <div className="space-y-4 p-6">
      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-gray-900">Actual Costs</h2>
          <div
            data-automation-id="JobActualTab-time-expenses"
            className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-right"
          >
            <div className="text-xs text-slate-500">Time &amp; Expenses</div>
            <div className="font-semibold tabular-nums text-gray-900">
              {summary ? formatCurrency(summary.rev) : '—'}
            </div>
          </div>
        </div>
        <div className="mt-3">
          <CostLineGrid
            jobId={jobId}
            kind="actual"
            materialsMarkup={String(companyDefaults.materials_markup)}
            wageRate={String(companyDefaults.wage_rate)}
          />
        </div>
      </section>
    </div>
  )
}
