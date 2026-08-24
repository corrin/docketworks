import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobJobsQuoteRetrieveOptions,
  jobJobsQuoteRetrieveQueryKey,
  xeroCreateQuoteMutation,
  xeroDeleteQuoteMutation,
  xeroPingRetrieveOptions,
} from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatCurrency, formatDate } from '@/lib/format'

import { invalidateJobViews } from '../invalidateJobViews'

interface XeroQuoteCardProps {
  jobId: string
}

/**
 * The job's Xero quote: create (total-only or per-line breakdown), open in
 * Xero, delete. A job holds at most one quote (Quote↔Job is one-to-one), so
 * the card is a single-document fork, not a list like invoices. Quote state
 * is server truth — after every change the quote and full-job queries are
 * re-read, never adjusted locally.
 */
export function XeroQuoteCard({ jobId }: XeroQuoteCardProps) {
  const queryClient = useQueryClient()
  const quoteQuery = useQuery(jobJobsQuoteRetrieveOptions({ path: { job_id: jobId } }))
  const ping = useQuery(xeroPingRetrieveOptions())
  const xeroConnected = ping.data?.connected ?? false

  const [showExportDialog, setShowExportDialog] = useState(false)
  const createQuote = useMutation(xeroCreateQuoteMutation())
  const deleteQuote = useMutation(xeroDeleteQuoteMutation())

  // Enveloped ({quote: ...|null}): the axios client coerces a bare JSON
  // null body to {}, so a top-level nullable body cannot round-trip.
  const quote = quoteQuery.data?.quote ?? null

  const reloadQuoteState = () => {
    void queryClient.invalidateQueries({
      queryKey: jobJobsQuoteRetrieveQueryKey({ path: { job_id: jobId } }),
    })
    // Invalidating only the quote query was rejected: job.quoted flipped,
    // which the header and other tabs read from the full job — and creating
    // or deleting a Xero quote writes a JobEvent
    // (apps/xero/documents/quote.py), so the timeline moves with it.
    void invalidateJobViews(queryClient, jobId)
  }

  const executeCreate = (breakdown: boolean) => {
    if (createQuote.isPending) return
    setShowExportDialog(false)
    createQuote.mutate(
      { path: { job_id: jobId }, body: { breakdown } },
      {
        onSuccess: (response) => {
          toast.success('Quote created successfully!')
          // A created quote can still carry warnings (e.g. the history note
          // failed); each one is the user's to act on.
          response.messages?.forEach((message) => toast.warning(message))
          reloadQuoteState()
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to create the quote.'))
        },
      },
    )
  }

  const executeDelete = () => {
    if (deleteQuote.isPending) return
    // Same guard as a cost-line delete: one click must not silently void a
    // real Xero document.
    if (!window.confirm('Delete this quote in Xero?')) return
    deleteQuote.mutate(
      { path: { job_id: jobId } },
      {
        onSuccess: () => {
          toast.success('Quote deleted successfully!')
          reloadQuoteState()
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to delete the quote.'))
        },
      },
    )
  }

  return (
    <aside className="rounded-xl border border-slate-200 bg-white">
      <div className="px-3 pt-3 pb-2">
        <h3 className="text-base font-semibold text-gray-900">Quote Management</h3>
        <p className="text-xs text-slate-500">Send this quote to Xero.</p>
      </div>

      <div className="px-3 pb-3">
        {quoteQuery.isPending ? (
          // Pending must not read as absent: rendering the create state here
          // would offer a doomed duplicate-create on a job that already has
          // a quote (same rule as the failed-read branch below).
          <div className="py-4 text-center text-sm text-slate-500">Checking for a quote…</div>
        ) : quoteQuery.isError && quoteQuery.data === undefined ? (
          // A failed read must not masquerade as "no quote": that state
          // offers a create button that would then be refused as a duplicate.
          <div className="py-4 text-center text-sm text-red-700">
            Could not load this job&apos;s Xero quote. Reload the page.
          </div>
        ) : quote ? (
          <div className="space-y-3">
            <div className="rounded-md bg-slate-50 p-3 text-sm">
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-900">{quote.number ?? 'Quote'}</span>
                <span className="rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-700">
                  {quote.status}
                </span>
              </div>
              <div className="mt-1 text-[11px] text-slate-500">{formatDate(quote.date)}</div>
              <div className="mt-2 font-semibold tabular-nums text-slate-900">
                {formatCurrency(quote.total_excl_tax)}{' '}
                <span className="text-xs font-normal text-slate-500">excl GST</span>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <Button
                variant="outline"
                size="sm"
                data-automation-id="JobQuoteTab-open-in-xero"
                disabled={!quote.online_url}
                onClick={() => {
                  if (quote.online_url) {
                    // noopener: the Xero tab must not get a handle on this
                    // window (reverse tabnabbing).
                    window.open(quote.online_url, '_blank', 'noopener,noreferrer')
                  } else {
                    toast.error('No online URL available for this quote.')
                  }
                }}
              >
                <ExternalLink className="mr-1 h-4 w-4" />
                Open in Xero
              </Button>
              <Button
                variant="destructive"
                size="sm"
                data-automation-id="JobQuoteTab-delete-quote"
                disabled={deleteQuote.isPending}
                onClick={executeDelete}
              >
                {deleteQuote.isPending ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="mr-1 h-4 w-4" />
                )}
                {deleteQuote.isPending ? 'Deleting…' : 'Delete Quote'}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 py-2">
            <p className="text-sm text-gray-500">No quotes for this project</p>
            <button
              type="button"
              data-automation-id="JobQuoteTab-create-quote"
              disabled={createQuote.isPending || !xeroConnected}
              className="flex items-center gap-2 rounded-md bg-orange-600 px-4 py-2 text-white hover:bg-orange-700 focus:ring-2 focus:ring-orange-500 focus:outline-none disabled:opacity-50"
              onClick={() => setShowExportDialog(true)}
            >
              {createQuote.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {createQuote.isPending
                ? 'Creating...'
                : xeroConnected
                  ? 'Create Quote'
                  : ping.isPending
                    ? 'Checking Xero…'
                    : 'Login to Xero first'}
            </button>
            {ping.isError && (
              // A failed status check is not "logged out" — say what actually
              // happened instead of sending the user to re-authenticate.
              <p className="text-center text-xs text-red-700">
                Could not check the Xero connection. Reload the page.
              </p>
            )}
          </div>
        )}
      </div>

      <Dialog open={showExportDialog} onOpenChange={setShowExportDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Export Quote to Xero</DialogTitle>
            <DialogDescription>Choose how you want to export this quote to Xero</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            <Button
              className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
              data-automation-id="JobQuoteTab-send-total-only"
              disabled={createQuote.isPending}
              onClick={() => executeCreate(false)}
            >
              <span className="font-semibold">Send Total Only</span>
              <span className="text-xs font-normal opacity-90">
                Export as a single line item with the total amount (Default)
              </span>
            </Button>
            <Button
              variant="outline"
              className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
              data-automation-id="JobQuoteTab-send-breakdown"
              disabled={createQuote.isPending}
              onClick={() => executeCreate(true)}
            >
              <span className="font-semibold">Send Breakdown</span>
              <span className="text-xs font-normal opacity-70">
                Export each cost line as its own line item
              </span>
            </Button>
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              disabled={createQuote.isPending}
              onClick={() => setShowExportDialog(false)}
            >
              Cancel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  )
}
