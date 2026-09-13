import { useQuery, useSuspenseQuery } from '@tanstack/react-query'

import { getFullJobOptions, jobJobsCostSetsRetrieveOptions } from '@/api'
import { formatCurrency } from '@/lib/format'
import { EntryGridSection } from '@/features/shared/EntryGridSection'
import { CostLineGrid } from './CostLineGrid'
import { CostSetSummaryPanel } from './CostSetSummaryPanel'

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
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <EntryGridSection
          title="Actual Costs"
          actions={
            <div
              data-automation-id="JobActualTab-time-expenses"
              className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-right"
            >
              <div className="text-xs text-slate-500">Time &amp; Expenses</div>
              <div className="font-semibold tabular-nums text-gray-900">
                {summary ? formatCurrency(summary.rev) : '—'}
              </div>
            </div>
          }
        >
          <CostLineGrid
            jobId={jobId}
            kind="actual"
            materialsMarkup={String(companyDefaults.materials_markup)}
            wageRate={String(companyDefaults.wage_rate)}
          />
        </EntryGridSection>

        <div className="space-y-4 lg:sticky lg:top-4">
          <CostSetSummaryPanel
            title="Actual Summary"
            automationId="JobActualTab-summary"
            summary={summary}
            isError={costSetQuery.isError}
          />
        </div>
      </div>
    </div>
  )
}
