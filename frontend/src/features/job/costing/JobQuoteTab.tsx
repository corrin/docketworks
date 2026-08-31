import { useState } from 'react'
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { BookOpen, Copy } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  getFullJobOptions,
  isApiErrorStatus,
  jobJobsCostSetsQuoteCopyFromEstimateCreateMutation,
  jobJobsCostSetsQuoteReviseRetrieveQueryKey,
  jobJobsCostSetsRetrieveOptions,
  jobJobsCostSetsRetrieveQueryKey,
  jobJobsQuoteRetrieveOptions,
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
import { formatCurrency } from '@/lib/format'
import { invalidateJobViews } from '../invalidateJobViews'
import { CostLineGrid } from './CostLineGrid'
import { CostSetSummaryPanel } from './CostSetSummaryPanel'
import { QuoteRevisionsDialog } from './QuoteRevisionsDialog'
import { XeroQuoteCard } from './XeroQuoteCard'

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

  // Cache share with XeroQuoteCard, not a second fetch: the archive dialog
  // must be able to warn that the exported quote will go stale.
  const xeroQuoteQuery = useQuery(jobJobsQuoteRetrieveOptions({ path: { job_id: jobId } }))
  const xeroQuote = xeroQuoteQuery.data?.quote ?? null

  const [showArchiveDialog, setShowArchiveDialog] = useState(false)
  const [showRevisionsDialog, setShowRevisionsDialog] = useState(false)
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
          // An archive-and-replace grew the revision history.
          void queryClient.invalidateQueries({
            queryKey: jobJobsCostSetsQuoteReviseRetrieveQueryKey({ path: { job_id: jobId } }),
          })
          // The costs summary and header totals read the quote through the
          // full-job payload, so the grid's query alone is not enough.
          void invalidateJobViews(queryClient, jobId)
        },
        onError: (error) => {
          // Fable: 409 is the contract's "this quote holds real work" answer,
          // not a failure: it opens the archive-and-replace decision instead
          // of a toast. The server owns the blank-vs-priced call — the client
          // never re-derives it from loaded lines that may be stale.
          if (isApiErrorStatus(error, 409)) {
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
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                data-automation-id="JobQuoteTab-revisions"
                onClick={() => setShowRevisionsDialog(true)}
              >
                <BookOpen className="mr-1 h-4 w-4" />
                Revisions
              </Button>
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
          <CostSetSummaryPanel
            title="Quote Summary"
            automationId="JobQuoteTab-summary"
            summary={summary}
            isError={costSetQuery.isError}
          />

          <XeroQuoteCard jobId={jobId} />
        </div>
      </div>

      <QuoteRevisionsDialog
        jobId={jobId}
        open={showRevisionsDialog}
        onOpenChange={setShowRevisionsDialog}
      />

      <Dialog open={showArchiveDialog} onOpenChange={setShowArchiveDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Replace this quote?</DialogTitle>
            <DialogDescription>
              {/* Both totals: the server judges "priced" on cost OR revenue,
                  so a cost-only or offsetting-adjustments quote would read
                  "$0.00" on revenue alone and invite discarding real work. */}
              The quote already has priced cost lines
              {summary
                ? ` totalling ${formatCurrency(summary.rev)} revenue and ${formatCurrency(summary.cost)} cost`
                : ''}
              . Archiving keeps them as a revision you can still see; the quote is then replaced
              with the current estimate. Any quote acceptance is cleared — the replaced figures are
              not what the customer accepted.
            </DialogDescription>
          </DialogHeader>
          {xeroQuote && (
            // Replacing the cost lines does not touch the Xero document, so
            // it silently goes stale. Say it where the decision is made.
            <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
              This quote was exported to Xero as <strong>{xeroQuote.number ?? 'a quote'}</strong>.
              Replacing the lines here does not update Xero — the exported quote will no longer
              match.
            </p>
          )}
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
