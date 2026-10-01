import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'

import { accountingReportsJobMovementRetrieveOptions } from '@/api'
import { QueryState } from '@/features/shared/QueryState'
import { isIsoDateString, mondayOf, shiftDate, spanFrom } from '@/lib/dates'
import { formatPercentage, localIsoDate } from '@/lib/format'
import { SummaryCard } from '@/features/shared/SummaryCard'

// The wire schema declares this response as an open object, so the shape the
// page relies on is pinned here and a drifted backend fails the query loudly
// instead of rendering blanks.
const countMetric = z.object({ count: z.number() })
const rateMetric = z.object({ rate: z.number() })
const jobMovementReport = z.object({
  metrics: z.object({
    draft_jobs_created: countMetric,
    quotes_submitted: countMetric,
    quotes_accepted: countMetric,
    jobs_won: countMetric,
    draft_conversion_rate: rateMetric,
    quote_acceptance_rate: rateMetric,
    workflow_paths: z.object({
      through_quotes: z.number(),
      skip_quotes: z.number(),
      quote_usage_percent: z.number(),
    }),
  }),
})

export interface DateRange {
  startDate: string
  endDate: string
}

/** The period, off the URL; the route writes this fortnight into a bare one. */
export interface JobMovementSearch {
  start?: string
  end?: string
}

export function jobMovementSearchFromUrl(search: Record<string, unknown>): JobMovementSearch {
  return {
    start:
      typeof search.start === 'string' && isIsoDateString(search.start) ? search.start : undefined,
    end: typeof search.end === 'string' && isIsoDateString(search.end) ? search.end : undefined,
  }
}

const FORTNIGHT_DAYS = 14

export function thisFortnight(): DateRange {
  return spanFrom(mondayOf(localIsoDate()), FORTNIGHT_DAYS)
}

function lastFortnight(): DateRange {
  return spanFrom(shiftDate(mondayOf(localIsoDate()), -FORTNIGHT_DAYS), FORTNIGHT_DAYS)
}

export interface JobMovementReportPageProps {
  range: DateRange
  /** Writes the period into the URL (docs/design-language.md, "Report
      filters live in the URL"); the route re-renders the page with it. */
  onRangeChange: (range: DateRange) => void
}

/**
 * Job movement report. Only the fortnight presets exist; the custom date
 * range, comparison and baseline controls ship with the slice that asserts
 * on them.
 */
export function JobMovementReportPage({ range, onRangeChange }: JobMovementReportPageProps) {
  const report = useQuery({
    ...accountingReportsJobMovementRetrieveOptions({
      query: { start_date: range.startDate, end_date: range.endDate },
    }),
    select: (data: unknown) => jobMovementReport.parse(data),
  })

  return (
    <div className="min-h-screen p-6">
      <div className="flex items-center justify-between">
        <h1
          className="text-xl font-bold text-gray-900"
          data-automation-id="JobMovementReport-title"
        >
          Job Movement Report
        </h1>
        <div className="flex space-x-2">
          <button
            type="button"
            data-automation-id="JobMovementReport-this-fortnight"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm transition-colors hover:bg-gray-50"
            onClick={() => onRangeChange(thisFortnight())}
          >
            This Fortnight
          </button>
          <button
            type="button"
            data-automation-id="JobMovementReport-last-fortnight"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm transition-colors hover:bg-gray-50"
            onClick={() => onRangeChange(lastFortnight())}
          >
            Last Fortnight
          </button>
        </div>
      </div>

      <QueryState
        isPending={report.isPending}
        isError={report.isError}
        onRetry={() => void report.refetch()}
        loadingLabel="Loading job movement report..."
        loadingAutomationId="JobMovementReport-loading"
        errorLabel="Failed to load the job movement report."
      >
        {report.isSuccess && (
          <>
            <div
              data-automation-id="JobMovementReport-summary-cards"
              className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
            >
              <SummaryCard
                label="Draft Jobs Created"
                valueAutomationId="JobMovementReport-draft-jobs-count"
              >
                {report.data.metrics.draft_jobs_created.count}
              </SummaryCard>
              <SummaryCard
                label="Quotes Submitted"
                valueAutomationId="JobMovementReport-quotes-submitted-count"
              >
                {report.data.metrics.quotes_submitted.count}
              </SummaryCard>
              <SummaryCard label="Jobs Won" valueAutomationId="JobMovementReport-jobs-won-count">
                {report.data.metrics.jobs_won.count}
              </SummaryCard>
              <SummaryCard
                label="Draft Conversion Rate"
                valueAutomationId="JobMovementReport-conversion-rate-value"
              >
                {formatPercentage(report.data.metrics.draft_conversion_rate.rate)}
              </SummaryCard>
            </div>

            <div
              data-automation-id="JobMovementReport-additional-metrics"
              className="mt-6 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
            >
              <h2 className="text-sm font-semibold text-gray-900">Additional Metrics</h2>
              <dl className="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <dt className="text-gray-500">Quotes Accepted</dt>
                  <dd className="font-medium text-gray-900">
                    {report.data.metrics.quotes_accepted.count}
                  </dd>
                </div>
                <div>
                  <dt className="text-gray-500">Quote Acceptance Rate</dt>
                  <dd className="font-medium text-gray-900">
                    {formatPercentage(report.data.metrics.quote_acceptance_rate.rate)}
                  </dd>
                </div>
                <div>
                  <dt className="text-gray-500">Through Quotes / Skipped</dt>
                  <dd className="font-medium text-gray-900">
                    {report.data.metrics.workflow_paths.through_quotes} /{' '}
                    {report.data.metrics.workflow_paths.skip_quotes}
                  </dd>
                </div>
                <div>
                  <dt className="text-gray-500">Quote Usage</dt>
                  <dd className="font-medium text-gray-900">
                    {formatPercentage(report.data.metrics.workflow_paths.quote_usage_percent)}
                  </dd>
                </div>
              </dl>
            </div>
          </>
        )}
      </QueryState>
    </div>
  )
}
