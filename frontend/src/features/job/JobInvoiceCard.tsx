import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobJobsInvoicesRetrieveOptions,
  xeroCreateInvoiceMutation,
  xeroDeleteInvoiceMutation,
  xeroPingRetrieveOptions,
} from '@/api'
import type { XeroInvoiceCreateIn } from '@/api'
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

type InvoiceMode = XeroInvoiceCreateIn['mode']

// Job statuses that mean the work itself is done. Purely a wording choice —
// invoicing stays available at every status.
const COMPLETED_STATUSES = new Set(['recently_completed', 'archived'])

interface JobInvoiceCardProps {
  jobId: string
  pricingMethodology: string
  remainingToInvoice: number
  jobStatus: string
  paid: boolean
  onInvoicesChanged: () => void
}

/**
 * The job's invoice list plus the create-invoice dialog. The balance is only
 * correct against the current invoice set, so after any change the parent
 * re-reads it from the server rather than adjusting it locally.
 */
export function JobInvoiceCard({
  jobId,
  pricingMethodology,
  remainingToInvoice,
  jobStatus,
  paid,
  onInvoicesChanged,
}: JobInvoiceCardProps) {
  const invoicesQuery = useQuery(jobJobsInvoicesRetrieveOptions({ path: { job_id: jobId } }))
  const ping = useQuery(xeroPingRetrieveOptions())
  const xeroConnected = ping.data?.connected ?? false
  const invoices = invoicesQuery.data?.invoices ?? []

  const [showModal, setShowModal] = useState(false)
  const [selectedMode, setSelectedMode] = useState<InvoiceMode | null>(null)
  const [percentInput, setPercentInput] = useState('')
  const [amountInput, setAmountInput] = useState('')

  const createInvoice = useMutation(xeroCreateInvoiceMutation())
  const deleteInvoice = useMutation(xeroDeleteInvoiceMutation())

  const workComplete = COMPLETED_STATUSES.has(jobStatus)

  const modalDescription = !workComplete
    ? 'Request payment in advance, take a deposit, or raise a progress invoice.'
    : pricingMethodology === 'fixed_price'
      ? 'Invoice the remaining quote balance.'
      : 'Invoice the remaining Time & Materials costs.'
  const fullInvoiceLabel = workComplete
    ? 'Invoice remaining quote balance'
    : 'Invoice full amount in advance'
  const costsToDateLabel = workComplete ? 'Invoice remaining T&M costs' : 'Invoice costs to date'
  const customAmountHint = workComplete
    ? 'Invoice a specific dollar amount'
    : 'Invoice a deposit or progress payment of a specific amount'

  const openModal = () => {
    setSelectedMode(null)
    setPercentInput('')
    setAmountInput('')
    setShowModal(true)
  }

  const selectMode = (mode: InvoiceMode) => {
    setSelectedMode(mode)
    setPercentInput('')
    setAmountInput('')
  }

  const afterInvoiceChange = () => {
    onInvoicesChanged()
    // refetch() resolves even when the fetch fails (it only rejects under
    // throwOnError), so the failure signal is on the result, not in a catch.
    void invoicesQuery.refetch().then((result) => {
      if (result.error) {
        toast.error('Invoice saved, but the list could not be refreshed. Reload the job.')
      }
    })
  }

  const executeCreate = (mode: InvoiceMode) => {
    if (createInvoice.isPending) return

    let percent: number | undefined
    let amount: number | undefined
    if (mode === 'invoice_percent') {
      const pct = parseFloat(percentInput)
      if (isNaN(pct) || pct <= 0 || pct > 100) {
        toast.error('Please enter a valid percentage (1-100)')
        return
      }
      percent = pct
    }
    if (mode === 'invoice_amount') {
      const amt = parseFloat(amountInput)
      if (isNaN(amt) || amt <= 0) {
        toast.error('Please enter a valid amount')
        return
      }
      amount = amt
    }

    setShowModal(false)
    createInvoice.mutate(
      {
        path: { job_id: jobId },
        body: {
          mode,
          ...(percent !== undefined && { percent }),
          ...(amount !== undefined && { amount }),
        },
      },
      {
        onSuccess: (response) => {
          toast.success('Invoice created successfully!')
          // A created invoice can still carry warnings (e.g. the workshop
          // PDF attachment failed); each one is the user's to act on.
          response.messages?.forEach((message) => toast.warning(message))
          afterInvoiceChange()
        },
        onError: (error) => {
          toast.error(
            `Failed to create invoice: ${apiErrorMessage(
              error,
              'Unexpected error while trying to create invoice.',
            )}`,
          )
        },
      },
    )
  }

  const executeDelete = (invoiceXeroId: string) => {
    if (deleteInvoice.isPending) return
    deleteInvoice.mutate(
      { path: { job_id: jobId }, query: { xero_invoice_id: invoiceXeroId } },
      {
        onSuccess: () => {
          toast.success('Invoice deleted successfully!')
          afterInvoiceChange()
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to delete invoice.'))
        },
      },
    )
  }

  return (
    <aside className="rounded-xl border border-slate-200 bg-white">
      <div className="px-3 pt-3 pb-2">
        <h3 className="text-base font-semibold text-gray-900">
          Invoices <span className="text-sm text-slate-400">({invoices.length})</span>
        </h3>
        <p className="text-xs text-slate-500">Manage invoices for this job.</p>
      </div>

      <div className="max-h-[20rem] overflow-y-auto px-2 pb-2">
        {invoicesQuery.isError ? (
          // A failed read must not masquerade as the empty state: "No
          // invoices" tells staff it is safe to invoice again.
          <div className="py-6 text-center text-red-700">
            Could not load this job&apos;s invoices. Reload the page.
          </div>
        ) : invoices.length === 0 ? (
          <div className="py-6 text-center text-gray-500">No invoices for this project</div>
        ) : (
          <ul
            role="list"
            data-automation-id="JobInvoiceCard-list"
            className="divide-y divide-slate-200 rounded-md bg-white"
          >
            {invoices.map((invoice) => (
              <li
                key={invoice.id}
                className="flex items-center gap-3 px-3 py-1.5 hover:bg-slate-50"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm leading-5 font-medium text-slate-900">
                      {invoice.number}
                    </span>
                    <span
                      className={`rounded-full px-1.5 py-0.5 text-[10px] ${
                        invoice.status === 'PAID'
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {invoice.status}
                    </span>
                  </div>
                  <div className="text-[11px] leading-4 text-slate-500">
                    {formatDate(invoice.date)}
                  </div>
                </div>

                <div className="shrink-0 text-sm font-semibold tabular-nums text-slate-900">
                  {formatCurrency(invoice.total_excl_tax)}
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    data-automation-id={`JobInvoiceCard-open-${invoice.id}`}
                    aria-label={`Open invoice ${invoice.number} in Xero`}
                    disabled={!invoice.online_url}
                    onClick={() => {
                      if (invoice.online_url) {
                        window.open(invoice.online_url, '_blank')
                      } else {
                        toast.error('No online URL available for this invoice.')
                      }
                    }}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="destructive"
                    size="icon-sm"
                    data-automation-id={`JobInvoiceCard-delete-${invoice.id}`}
                    aria-label={`Delete invoice ${invoice.number}`}
                    disabled={deleteInvoice.isPending}
                    onClick={() => executeDelete(invoice.xero_id)}
                  >
                    {deleteInvoice.isPending &&
                    deleteInvoice.variables?.query.xero_invoice_id === invoice.xero_id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-slate-200" />
      <div className="flex flex-col items-center gap-2 p-4">
        {remainingToInvoice > 0 ? (
          <button
            type="button"
            data-automation-id="JobFinishTab-create-invoice"
            disabled={createInvoice.isPending || paid || !xeroConnected}
            className="flex items-center gap-2 rounded-md bg-orange-600 px-4 py-2 text-white hover:bg-orange-700 focus:ring-2 focus:ring-orange-500 focus:outline-none disabled:opacity-50"
            onClick={openModal}
          >
            {createInvoice.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {createInvoice.isPending
              ? 'Creating...'
              : xeroConnected
                ? 'Create Invoice'
                : 'Login to Xero first'}
          </button>
        ) : (
          <p
            data-automation-id="JobFinishTab-fully-invoiced"
            className="text-center text-xs text-slate-500"
          >
            Fully invoiced — nothing further to invoice.
          </p>
        )}

        {paid && (
          <p className="text-center text-xs text-slate-500">
            Job is marked as <strong>Paid</strong>. Unmark &quot;Paid&quot; to create another
            invoice.
          </p>
        )}
      </div>

      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create Invoice</DialogTitle>
            <DialogDescription>{modalDescription}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-1 rounded-lg bg-slate-50 p-3 text-sm">
              <div className="flex justify-between border-t pt-1">
                <span className="font-medium text-slate-700">Current amount to invoice</span>
                <span className="font-bold tabular-nums text-orange-600">
                  {formatCurrency(remainingToInvoice)}
                </span>
              </div>
            </div>

            <div className="space-y-3">
              {pricingMethodology === 'fixed_price' ? (
                <>
                  <Button
                    className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
                    data-automation-id="JobFinishTab-mode-invoice-full"
                    disabled={createInvoice.isPending}
                    onClick={() => executeCreate('invoice_full')}
                  >
                    <span className="font-semibold">{fullInvoiceLabel}</span>
                    <span className="text-xs font-normal opacity-90">
                      {formatCurrency(remainingToInvoice)} excl GST
                    </span>
                  </Button>

                  <Button
                    variant="outline"
                    className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
                    data-automation-id="JobFinishTab-mode-invoice-percent"
                    disabled={createInvoice.isPending}
                    onClick={() => selectMode('invoice_percent')}
                  >
                    <span className="font-semibold">Invoice % of quote</span>
                    <span className="text-xs font-normal opacity-70">
                      Invoice a cumulative percentage of the quoted amount
                    </span>
                  </Button>
                  {selectedMode === 'invoice_percent' && (
                    <div className="flex gap-2">
                      <input
                        type="number"
                        min="1"
                        max="100"
                        step="0.1"
                        placeholder="e.g. 50"
                        value={percentInput}
                        className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
                        onChange={(event) => setPercentInput(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            event.preventDefault()
                            executeCreate('invoice_percent')
                          }
                        }}
                      />
                      <Button
                        size="sm"
                        disabled={createInvoice.isPending}
                        onClick={() => executeCreate('invoice_percent')}
                      >
                        Confirm
                      </Button>
                    </div>
                  )}
                </>
              ) : (
                <Button
                  className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
                  data-automation-id="JobFinishTab-mode-invoice-costs-to-date"
                  disabled={createInvoice.isPending}
                  onClick={() => executeCreate('invoice_costs_to_date')}
                >
                  <span className="font-semibold">{costsToDateLabel}</span>
                  <span className="text-xs font-normal opacity-90">
                    {formatCurrency(remainingToInvoice)} excl GST
                  </span>
                </Button>
              )}

              <Button
                variant="outline"
                className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
                data-automation-id="JobFinishTab-mode-invoice-amount"
                disabled={createInvoice.isPending}
                onClick={() => selectMode('invoice_amount')}
              >
                <span className="font-semibold">Invoice $ amount</span>
                <span className="text-xs font-normal opacity-70">{customAmountHint}</span>
              </Button>
              {selectedMode === 'invoice_amount' && (
                <div className="flex gap-2">
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    placeholder="0.00"
                    value={amountInput}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
                    onChange={(event) => setAmountInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        executeCreate('invoice_amount')
                      }
                    }}
                  />
                  <Button
                    size="sm"
                    disabled={createInvoice.isPending}
                    onClick={() => executeCreate('invoice_amount')}
                  >
                    Confirm
                  </Button>
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              disabled={createInvoice.isPending}
              onClick={() => setShowModal(false)}
            >
              Cancel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  )
}
