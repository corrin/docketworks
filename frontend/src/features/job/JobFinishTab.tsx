import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobJobsCostsSummaryRetrieveOptions,
  jobJobsFinishPartialUpdateMutation,
  jobJobsFinishRetrieveOptions,
  jobJobsFinishRetrieveQueryKey,
  jobJobsInvoicesRetrieveQueryKey,
} from '@/api'
import type { CostSetSummaryOut, JobCompletionChecklistOut, JobDetail } from '@/api'
import { QueryState } from '@/features/shared/QueryState'
import { formatCurrency, formatPercentage } from '@/lib/format'

import { invalidateJobViews } from './invalidateJobViews'
import { JobInvoiceCard } from './JobInvoiceCard'

type ChecklistKey = keyof JobCompletionChecklistOut

const ALL_CHECKLIST_ITEMS: Array<{ key: ChecklistKey; label: string }> = [
  { key: 'foreman_signed_off', label: 'Has the supervisor signed off the job?' },
  { key: 'timesheets_collected', label: "Have you collected today's timesheet entries?" },
  { key: 'materials_checked', label: 'Are all materials used written correctly on the job sheet?' },
  { key: 'customer_called', label: 'Have you called the customer?' },
  { key: 'released', label: 'Has the job been handed over?' },
]

interface NormalizedCostSummary {
  cost: number
  rev: number
  hours: number
  profitMargin: number
}

const normalize = (summary: CostSetSummaryOut | null | undefined): NormalizedCostSummary => ({
  cost: summary?.cost ?? 0,
  rev: summary?.rev ?? 0,
  hours: summary?.hours ?? 0,
  profitMargin: summary?.profitMargin ?? 0,
})

function percentDiff(actual: number, reference: number): number {
  if (!reference) return 0
  return ((actual - reference) / reference) * 100
}

function signedPercent(value: number): string {
  return `${value > 0 ? '+' : ''}${formatPercentage(value)}`
}

const NUMBER = new Intl.NumberFormat('en-NZ', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})

function DiffCell({
  value,
  diff,
  goodWhenPositive,
  format,
}: {
  value: number
  diff: number
  goodWhenPositive: boolean
  format: (value: number) => string
}) {
  const isGood = goodWhenPositive ? diff >= 0 : diff <= 0
  const Icon: LucideIcon | null = diff > 0 ? ArrowUp : diff < 0 ? ArrowDown : null
  return (
    <span className={isGood ? 'font-bold text-green-600' : 'font-bold text-red-600'}>
      {format(value)}
      {diff !== 0 && Icon && (
        <>
          <Icon className="ml-1 inline h-4 w-4 align-text-bottom" />
          <span className={isGood ? 'text-green-600' : 'text-red-600'}>{signedPercent(diff)}</span>
        </>
      )}
    </span>
  )
}

interface JobFinishTabProps {
  jobId: string
  job: JobDetail
}

/**
 * Finish Job workspace: the server-owned customer balance, invoice card,
 * completion checklist, and the estimate/quote/actual comparison. Nothing
 * here recomputes money — every figure is formatted from what the server
 * sent (ADR 0046), so invoicing and display cannot disagree.
 */
export function JobFinishTab({ jobId, job }: JobFinishTabProps) {
  const queryClient = useQueryClient()
  const finishQuery = useQuery(jobJobsFinishRetrieveOptions({ path: { job_id: jobId } }))
  const costsQuery = useQuery(jobJobsCostsSummaryRetrieveOptions({ path: { job_id: jobId } }))
  const checklistSave = useMutation(jobJobsFinishPartialUpdateMutation())

  const summary = finishQuery.data?.summary ?? null
  const checklist = finishQuery.data?.checklist ?? null
  const loading = finishQuery.isPending || costsQuery.isPending
  // A failed FIRST load is the error state; an errored background refetch
  // keeps the working tab on screen instead of unmounting it under the user.
  const loadError =
    (finishQuery.isError && finishQuery.data === undefined) ||
    (costsQuery.isError && costsQuery.data === undefined)

  const estimate = normalize(costsQuery.data?.estimate)
  const quote = normalize(costsQuery.data?.quote)
  const actual = normalize(costsQuery.data?.actual)
  const hasValidQuoteData = Boolean(costsQuery.data?.quote && (quote.cost > 0 || quote.rev > 0))

  const isTimeMaterials = job.pricing_methodology === 'time_materials'
  const showQuoteColumn = !isTimeMaterials && (hasValidQuoteData || quote.cost > 0 || quote.rev > 0)

  // Timesheets only exist to invoice on a T&M job; a quoted job is never asked.
  const checklistItems = isTimeMaterials
    ? ALL_CHECKLIST_ITEMS
    : ALL_CHECKLIST_ITEMS.filter((item) => item.key !== 'timesheets_collected')

  const jobValueLabel =
    job.pricing_methodology === 'fixed_price'
      ? 'Quote total (excl GST)'
      : 'Job value to date (excl GST)'

  // Invoicing changed the balance, so the server is re-read rather than the
  // figure adjusted locally; a failed reload surfaces as the query's error
  // state instead of leaving the pre-invoice figure on screen looking current.
  const reloadFinishData = () => {
    void queryClient.invalidateQueries({
      queryKey: jobJobsFinishRetrieveQueryKey({ path: { job_id: jobId } }),
    })
    void queryClient.invalidateQueries({
      queryKey: jobJobsInvoicesRetrieveQueryKey({ path: { job_id: jobId } }),
    })
    // Invalidating only the finish/invoice queries was rejected: creating or
    // deleting an invoice writes a JobEvent and bumps the job
    // (apps/xero/documents/invoice.py), so both of the job's views moved with
    // it — the timeline gained an entry and the ETag the header's next
    // If-Match carries is now stale.
    void invalidateJobViews(queryClient, jobId)
  }

  const toggleChecklist = (key: ChecklistKey, checked: boolean) => {
    checklistSave.mutate(
      { path: { job_id: jobId }, body: { [key]: checked } },
      {
        onSuccess: (response) => {
          queryClient.setQueryData(
            jobJobsFinishRetrieveQueryKey({ path: { job_id: jobId } }),
            response,
          )
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to save checklist'))
        },
      },
    )
  }

  // --- KAN-222 labour hours ---
  const labourBudgetHours =
    job.pricing_methodology === 'fixed_price' && hasValidQuoteData ? quote.hours : estimate.hours
  const labourRemainingHours = Math.max(labourBudgetHours - actual.hours, 0)
  const labourOverrunHours = Math.max(actual.hours - labourBudgetHours, 0)

  const costRef = isTimeMaterials || !showQuoteColumn ? estimate.cost : quote.cost
  const revRef = isTimeMaterials || !showQuoteColumn ? estimate.rev : quote.rev
  const pmRef = isTimeMaterials || !showQuoteColumn ? estimate.profitMargin : quote.profitMargin
  const hoursRef = isTimeMaterials || !showQuoteColumn ? estimate.hours : quote.hours

  const costDiff = percentDiff(actual.cost, costRef)
  const revenueDiff = percentDiff(actual.rev, revRef)
  const profitDiff = percentDiff(actual.profitMargin, pmRef)
  const hoursDiff = percentDiff(actual.hours, hoursRef)

  const quoteDeviation = Math.abs(percentDiff(actual.cost, quote.cost))
  const quoteStatus: 'nodata' | 'good' | 'amber' | 'red' =
    !showQuoteColumn || !hasValidQuoteData || quote.cost === 0
      ? 'nodata'
      : quoteDeviation <= 20
        ? 'good'
        : quoteDeviation <= 40
          ? 'amber'
          : 'red'
  const QuoteAccuracyIcon =
    quoteStatus === 'good' ? CheckCircle : quoteStatus === 'amber' ? AlertTriangle : XCircle
  const quoteAccuracyClass =
    quoteStatus === 'good'
      ? 'text-green-600'
      : quoteStatus === 'amber'
        ? 'text-yellow-600'
        : quoteStatus === 'red'
          ? 'text-red-600'
          : 'text-gray-500'

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white p-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Finish Job</h2>
          <p className="text-sm text-gray-500">
            {isTimeMaterials
              ? 'Compare Estimate and Actual cost sets for this Time & Materials job'
              : !showQuoteColumn
                ? 'Compare Estimate and Actual cost sets for this job (no quote available)'
                : 'Compare Estimate, Quote, and Actual cost sets with visual performance indicators'}
          </p>
        </div>
      </div>

      <QueryState
        isPending={loading}
        // No fabricated placeholder: a failed load must not render as a
        // settled $0 job.
        isError={loadError || !summary || !checklist}
        loadingNode={
          <div className="flex items-center justify-center py-12">
            <div className="text-center">
              <div className="mx-auto mb-2 h-8 w-8 animate-spin rounded-full border-b-2 border-blue-600" />
              <p className="text-gray-500">Loading job financials...</p>
            </div>
          </div>
        }
        errorNode={
          <div
            data-automation-id="JobFinishTab-load-error"
            className="rounded-lg border border-red-200 bg-white p-6 text-center"
          >
            <p className="font-medium text-red-700">Could not load this job&apos;s financials.</p>
            <p className="mt-1 text-sm text-slate-600">Reload the page.</p>
          </div>
        }
      >
        {summary && checklist && (
          <>
            <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1fr_360px]">
              <section
                data-automation-id="JobFinishTab-balance"
                className="rounded-xl border border-slate-200 bg-white p-4"
              >
                <h3 className="text-base font-semibold text-gray-900">Customer balance</h3>

                <dl className="mt-3 space-y-1.5 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-slate-600">{jobValueLabel}</dt>
                    <dd className="font-medium tabular-nums">
                      {formatCurrency(Number(summary.job_value_excl_gst))}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-600">Already invoiced (excl GST)</dt>
                    <dd className="font-medium tabular-nums">
                      {formatCurrency(Number(summary.valid_invoiced_excl_gst))}
                    </dd>
                  </div>
                  <div className="flex justify-between border-t border-slate-200 pt-1.5">
                    <dt className="text-slate-600">Still to invoice (excl GST)</dt>
                    <dd
                      data-automation-id="JobFinishTab-remaining-excl-gst"
                      className="font-medium tabular-nums"
                    >
                      {formatCurrency(Number(summary.remaining_to_invoice_excl_gst))}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-600">GST</dt>
                    <dd
                      data-automation-id="JobFinishTab-remaining-gst"
                      className="font-medium tabular-nums"
                    >
                      {formatCurrency(Number(summary.remaining_gst))}
                    </dd>
                  </div>
                  {Number(summary.outstanding_invoiced_incl_gst) > 0 && (
                    <div className="flex justify-between">
                      <dt className="text-slate-600">Unpaid invoices (incl GST)</dt>
                      <dd
                        data-automation-id="JobFinishTab-outstanding-incl-gst"
                        className="font-medium tabular-nums"
                      >
                        {formatCurrency(Number(summary.outstanding_invoiced_incl_gst))}
                      </dd>
                    </div>
                  )}
                  <div className="mt-1 flex items-baseline justify-between border-t-2 border-slate-300 pt-2">
                    <dt className="font-semibold text-slate-900">Total to pay</dt>
                    <dd
                      data-automation-id="JobFinishTab-total-to-pay"
                      className="text-2xl font-bold tabular-nums text-emerald-700"
                    >
                      {formatCurrency(Number(summary.total_to_pay_incl_gst))}
                    </dd>
                  </div>
                </dl>

                {Number(summary.over_invoiced_excl_gst) > 0 && (
                  <div
                    data-automation-id="JobFinishTab-over-invoiced"
                    className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
                  >
                    <strong>
                      Job appears over-invoiced by{' '}
                      {formatCurrency(Number(summary.over_invoiced_excl_gst))}
                    </strong>{' '}
                    (excl GST). The job value may be out of date, or invoicing may need correcting.
                  </div>
                )}
              </section>

              <JobInvoiceCard
                jobId={jobId}
                pricingMethodology={job.pricing_methodology}
                remainingToInvoice={Number(summary.remaining_to_invoice_excl_gst)}
                jobStatus={job.job_status}
                paid={job.paid}
                onInvoicesChanged={reloadFinishData}
              />
            </div>

            <section
              data-automation-id="JobFinishTab-checklist"
              className="rounded-xl border border-slate-200 bg-white p-4"
            >
              <h3 className="text-base font-semibold text-gray-900">Completion checklist</h3>
              <p className="mb-3 text-xs text-slate-500">Self-checklist.</p>

              <div className="space-y-2">
                {checklistItems.map((item) => (
                  <label key={item.key} className="flex cursor-pointer items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={checklist[item.key]}
                      data-automation-id={`JobFinishTab-checklist-${item.key}`}
                      className="mt-0.5 h-4 w-4 rounded border-slate-300"
                      disabled={checklistSave.isPending}
                      onChange={(event) => toggleChecklist(item.key, event.target.checked)}
                    />
                    <span className="text-slate-800">{item.label}</span>
                  </label>
                ))}
              </div>
            </section>

            <div
              data-automation-id="JobFinishTab-labour-hours"
              className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3"
            >
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="text-[11px] tracking-wide text-slate-500 uppercase">
                  Labour budget
                </div>
                <div
                  data-automation-id="JobFinishTab-labour-budget"
                  className="text-lg font-semibold tabular-nums text-slate-900"
                >
                  {NUMBER.format(labourBudgetHours)}
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="text-[11px] tracking-wide text-slate-500 uppercase">Hours used</div>
                <div
                  data-automation-id="JobFinishTab-labour-used"
                  className="text-lg font-semibold tabular-nums text-slate-900"
                >
                  {NUMBER.format(actual.hours)}
                </div>
              </div>
              <div
                className={`rounded-lg border bg-white p-3 ${
                  labourOverrunHours > 0 ? 'border-red-200 bg-red-50' : 'border-slate-200'
                }`}
              >
                <div className="text-[11px] tracking-wide text-slate-500 uppercase">
                  {labourOverrunHours > 0 ? 'Overrun' : 'Hours remaining'}
                </div>
                <div
                  data-automation-id="JobFinishTab-labour-remaining"
                  className={`text-lg font-semibold tabular-nums ${
                    labourOverrunHours > 0 ? 'text-red-700' : 'text-slate-900'
                  }`}
                >
                  {NUMBER.format(
                    labourOverrunHours > 0 ? labourOverrunHours : labourRemainingHours,
                  )}
                </div>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full rounded-lg border border-gray-200 bg-white text-sm">
                <thead>
                  <tr className="bg-gray-50">
                    <th className="px-4 py-3 text-left font-semibold text-gray-700">Metric</th>
                    <th className="px-4 py-3 text-center font-semibold text-blue-700">Estimate</th>
                    {showQuoteColumn && (
                      <th className="px-4 py-3 text-center font-semibold text-green-700">Quote</th>
                    )}
                    <th className="px-4 py-3 text-center font-semibold text-orange-700">Actual</th>
                  </tr>
                </thead>
                <tbody className="[&_td]:border-b [&_td]:border-gray-200 [&_th]:border-b [&_th]:border-gray-200">
                  <tr>
                    <td className="px-4 py-2 font-medium">Total Cost</td>
                    <td className="px-4 py-2 text-center">{formatCurrency(estimate.cost)}</td>
                    {showQuoteColumn && (
                      <td className="px-4 py-2 text-center">{formatCurrency(quote.cost)}</td>
                    )}
                    <td className="px-4 py-2 text-center">
                      <DiffCell
                        value={actual.cost}
                        diff={costDiff}
                        goodWhenPositive={false}
                        format={formatCurrency}
                      />
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-medium">Total Revenue</td>
                    <td className="px-4 py-2 text-center">{formatCurrency(estimate.rev)}</td>
                    {showQuoteColumn && (
                      <td className="px-4 py-2 text-center">{formatCurrency(quote.rev)}</td>
                    )}
                    <td className="px-4 py-2 text-center">
                      <DiffCell
                        value={actual.rev}
                        diff={revenueDiff}
                        goodWhenPositive
                        format={formatCurrency}
                      />
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-medium">Profit Margin</td>
                    <td className="px-4 py-2 text-center">
                      {signedPercent(estimate.profitMargin)}
                    </td>
                    {showQuoteColumn && (
                      <td className="px-4 py-2 text-center">{signedPercent(quote.profitMargin)}</td>
                    )}
                    <td className="px-4 py-2 text-center">
                      <DiffCell
                        value={actual.profitMargin}
                        diff={profitDiff}
                        goodWhenPositive
                        format={signedPercent}
                      />
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 font-medium">Total Hours</td>
                    <td className="px-4 py-2 text-center">{NUMBER.format(estimate.hours)}</td>
                    {showQuoteColumn && (
                      <td className="px-4 py-2 text-center">{NUMBER.format(quote.hours)}</td>
                    )}
                    <td className="px-4 py-2 text-center">
                      <DiffCell
                        value={actual.hours}
                        diff={hoursDiff}
                        goodWhenPositive={false}
                        format={(value) => NUMBER.format(value)}
                      />
                    </td>
                  </tr>
                </tbody>
              </table>

              {showQuoteColumn && (
                <div className="mt-6 flex flex-col gap-4 md:flex-row">
                  {quoteStatus !== 'nodata' ? (
                    <div className="flex flex-1 items-center gap-3 rounded-lg border border-gray-200 bg-white p-4">
                      <QuoteAccuracyIcon className={`h-8 w-8 ${quoteAccuracyClass}`} />
                      <div>
                        <div className="font-semibold text-gray-900">Quote Accuracy</div>
                        <div className={`text-lg font-bold ${quoteAccuracyClass}`}>
                          {signedPercent(percentDiff(actual.cost, quote.cost))}
                        </div>
                        <div className="text-xs text-gray-500">
                          Deviation of actual cost from quoted cost
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-1 items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4">
                      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-300">
                        <span className="text-sm text-gray-500">?</span>
                      </div>
                      <div>
                        <div className="font-semibold text-gray-500">Quote Accuracy</div>
                        <div className="text-sm text-gray-500">
                          {!quote.cost ? 'No quote data available' : 'No actual data available'}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </QueryState>
    </div>
  )
}
