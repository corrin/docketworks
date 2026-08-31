import { useState } from 'react'
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  getFullJobOptions,
  jobJobsCostSetsQuoteCopyFromEstimateCreateMutation,
  jobJobsCostSetsRetrieveOptions,
  jobJobsCostSetsRetrieveQueryKey,
} from '@/api'
import type { JobDetail } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatCurrency, formatPercentage } from '@/lib/format'
import { invalidateJobViews } from '../invalidateJobViews'
import { CostLineGrid } from './CostLineGrid'
import { XeroQuoteCard } from './XeroQuoteCard'

const HOURS = new Intl.NumberFormat('en-NZ', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})

interface JobQuoteTabProps {
  jobId: string
  job: JobDetail
}

/**
 * Quote workspace: the editable quote cost set, its server-owned summary,
 * and the Xero quote card. Nothing here recomputes money — every figure is
 * formatted from what the server sent (ADR 0046).
 */
export function JobQuoteTab({ jobId, job }: JobQuoteTabProps) {
  const queryClient = useQueryClient()
  // Cache hit: JobDetailPage already holds this query; company defaults ride
  // beside the job in its payload.
  const fullJob = useSuspenseQuery(getFullJobOptions({ path: { job_id: jobId } }))
  const companyDefaults = fullJob.data.data.company_defaults
  const costSetQuery = useQuery({
    ...jobJobsCostSetsRetrieveOptions({ path: { job_id: jobId, kind: 'quote' } }),
    enabled: job.pricing_methodology !== 'time_materials',
  })
  const summary = costSetQuery.data?.summary

  const [showArchiveDialog, setShowArchiveDialog] = useState(false)
  const copyFromEstimate = useMutation(jobJobsCostSetsQuoteCopyFromEstimateCreateMutation())

  const executeCopy = (archiveExisting: boolean) => {
    if (copyFromEstimate.isPending) return
    setShowArchiveDialog(false)
    copyFromEstimate.mutate(
      { path: { job_id: jobId }, body: { archive_existing: archiveExisting } },
      {
        onSuccess: (response) => {
          toast.success(response.message)
          void queryClient.invalidateQueries({
            queryKey: jobJobsCostSetsRetrieveQueryKey({ path: { job_id: jobId, kind: 'quote' } }),
          })
          // The costs summary and header totals read the quote through the
          // full-job payload, so the grid's query alone is not enough.
          void invalidateJobViews(queryClient, jobId)
        },
        onError: (error) => {
          // 409 is the contract's "this quote holds real work" answer, not a
          // failure: it opens the archive-and-replace decision instead of a
          // toast. The server owns the blank-vs-priced call — the client
          // never re-derives it from loaded lines that may be stale.
          if (error.response?.status === 409) {
            setShowArchiveDialog(true)
            return
          }
          toast.error(apiErrorMessage(error, 'Failed to copy from estimate.'))
        },
      },
    )
  }

  // The tab bar already hides this tab for T&M jobs; a direct ?tab=quote URL
  // must not render a broken grid over a cost set the backend refuses to push.
  if (job.pricing_methodology === 'time_materials') {
    return (
      <div className="p-6 text-sm text-gray-500">
        A time and materials job has no quote — costs are invoiced as they land.
      </div>
    )
  }

  return (
    <div className="space-y-4 p-6">
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1fr_320px]">
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">
              Quote Details
              {costSetQuery.data && (
                <span className="ml-2 text-sm font-normal text-slate-400">
                  Revision {costSetQuery.data.rev}
                </span>
              )}
            </h2>
            <Button
              variant="outline"
              size="sm"
              data-automation-id="JobQuoteTab-copy-from-estimate"
              disabled={copyFromEstimate.isPending}
              onClick={() => executeCopy(false)}
            >
              <Copy className="mr-1 h-4 w-4" />
              {copyFromEstimate.isPending ? 'Copying…' : 'Copy from Estimate'}
            </Button>
          </div>
          <div className="mt-3">
            <CostLineGrid
              jobId={jobId}
              kind="quote"
              materialsMarkup={String(companyDefaults.materials_markup)}
              wageRate={String(companyDefaults.wage_rate)}
            />
          </div>
        </section>

        <div className="space-y-4 lg:sticky lg:top-4">
          <section
            data-automation-id="JobQuoteTab-summary"
            className="rounded-xl border border-slate-200 bg-white p-4"
          >
            <h3 className="text-base font-semibold text-gray-900">Quote Summary</h3>
            {summary ? (
              <dl className="mt-3 space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <dt className="text-slate-600">Revenue</dt>
                  <dd className="font-semibold tabular-nums">{formatCurrency(summary.rev)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-600">Cost</dt>
                  <dd className="font-medium tabular-nums">{formatCurrency(summary.cost)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-600">Hours</dt>
                  <dd className="font-medium tabular-nums">{HOURS.format(summary.hours)}</dd>
                </div>
                <div className="flex justify-between border-t border-slate-200 pt-1.5">
                  <dt className="text-slate-600">Profit margin</dt>
                  <dd className="font-medium tabular-nums">
                    {/* null margin means undefined (zero revenue), not 0.0% */}
                    {summary.profitMargin === null ? '—' : formatPercentage(summary.profitMargin)}
                  </dd>
                </div>
              </dl>
            ) : costSetQuery.isError ? (
              // No fabricated zeros: a failed load must not read as a $0
              // quote. Data wins over a failed refetch — the last good
              // summary beats an error banner mid-edit.
              <p className="mt-2 text-sm font-medium text-red-700">
                Could not load the quote summary. Reload the page.
              </p>
            ) : (
              <p className="mt-2 text-sm text-slate-500">Loading…</p>
            )}
          </section>

          <XeroQuoteCard jobId={jobId} />
        </div>
      </div>

      <Dialog open={showArchiveDialog} onOpenChange={setShowArchiveDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Replace this quote?</DialogTitle>
            <DialogDescription>
              The quote already has priced cost lines
              {summary ? ` totalling ${formatCurrency(summary.rev)}` : ''}. Archiving keeps them as
              a revision you can still see; the quote is then replaced with the current estimate.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              disabled={copyFromEstimate.isPending}
              onClick={() => setShowArchiveDialog(false)}
            >
              Cancel
            </Button>
            <Button
              data-automation-id="JobQuoteTab-archive-and-replace"
              disabled={copyFromEstimate.isPending}
              onClick={() => executeCopy(true)}
            >
              Archive &amp; replace
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
