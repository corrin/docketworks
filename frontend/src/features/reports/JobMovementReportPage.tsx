import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'

import { accountingReportsJobMovementRetrieveOptions } from '@/api'
import { formatPercentage } from '@/lib/format'
import { SummaryCard } from './SummaryCard'

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

interface DateRange {
  startDate: string
  endDate: string
}

function toLocalDateString(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function mondayOfThisWeek(now: Date): Date {
  const monday = new Date(now)
  const day = monday.getDay()
  monday.setDate(monday.getDate() - day + (day === 0 ? -6 : 1))
  return monday
}

function fortnightFrom(monday: Date): DateRange {
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 13)
  return { startDate: toLocalDateString(monday), endDate: toLocalDateString(sunday) }
}

function thisFortnight(): DateRange {
  return fortnightFrom(mondayOfThisWeek(new Date()))
}

function lastFortnight(): DateRange {
  const monday = mondayOfThisWeek(new Date())
  monday.setDate(monday.getDate() - 14)
  return fortnightFrom(monday)
}

/**
 * Job movement report. Only the fortnight presets exist; the custom date
 * range, comparison and baseline controls ship with the slice that asserts
 * on them.
 */
export function JobMovementReportPage() {
  const [range, setRange] = useState<DateRange>(thisFortnight)

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
            onClick={() => setRange(thisFortnight())}
          >
            This Fortnight
          </button>
          <button
            type="button"
            data-automation-id="JobMovementReport-last-fortnight"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm transition-colors hover:bg-gray-50"
            onClick={() => setRange(lastFortnight())}
          >
            Last Fortnight
          </button>
        </div>
      </div>

      {report.isPending && (
        <div data-automation-id="JobMovementReport-loading" className="mt-8 text-gray-500">
          Loading job movement report...
        </div>
      )}

      {report.isError && (
        <div className="mt-8 text-red-600">
          Failed to load the job movement report.
          <button
            type="button"
            className="ml-2 underline"
            onClick={() => {
              void report.refetch()
            }}
          >
            Retry
          </button>
        </div>
      )}

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
    </div>
  )
}
