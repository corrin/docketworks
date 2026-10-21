import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, Trash2 } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  apiErrorType,
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
import { xeroInvoiceStatusLabel } from '@/features/shared/xeroInvoiceStatus'

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
  const { t } = useTranslation('job')
  const invoicesQuery = useQuery(jobJobsInvoicesRetrieveOptions({ path: { job_id: jobId } }))
  const ping = useQuery(xeroPingRetrieveOptions())
  const xeroConnected = ping.data?.connected ?? false
  const invoices = invoicesQuery.data?.invoices ?? []

  const [showModal, setShowModal] = useState(false)
  const [selectedMode, setSelectedMode] = useState<InvoiceMode | null>(null)
  const [percentInput, setPercentInput] = useState('')
  const [amountInput, setAmountInput] = useState('')
  // An approved invoice the server would not just delete, with its reason:
  // the user chooses between voiding it and a second invoice.
  const [voidOffer, setVoidOffer] = useState<{
    xeroId: string
    number: string
    reason: string
  } | null>(null)

  const createInvoice = useMutation(xeroCreateInvoiceMutation())
  const deleteInvoice = useMutation(xeroDeleteInvoiceMutation())

  const workComplete = COMPLETED_STATUSES.has(jobStatus)
  // Why a second invoice can't be raised right now; null when it can (ADR 0067).
  const secondInvoiceBlocked = paid
    ? t('invoiceCard.voidDialog.secondInvoiceBlocked.paid')
    : !xeroConnected
      ? t('invoiceCard.voidDialog.secondInvoiceBlocked.notConnected')
      : remainingToInvoice <= 0
        ? t('invoiceCard.voidDialog.secondInvoiceBlocked.fullyInvoiced')
        : null

  const modalDescription = !workComplete
    ? t('invoiceCard.description.inAdvance')
    : pricingMethodology === 'fixed_price'
      ? t('invoiceCard.description.remainingQuote')
      : t('invoiceCard.description.remainingTimeMaterials')
  const fullInvoiceLabel = workComplete
    ? t('invoiceCard.fullInvoice.remaining')
    : t('invoiceCard.fullInvoice.inAdvance')
  const costsToDateLabel = workComplete
    ? t('invoiceCard.costsToDate.remaining')
    : t('invoiceCard.costsToDate.toDate')
  const customAmountHint = workComplete
    ? t('invoiceCard.customAmountHint.complete')
    : t('invoiceCard.customAmountHint.inProgress')

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
        toast.error(t('invoiceCard.refreshFailed'))
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
        toast.error(t('invoiceCard.invalidPercent'))
        return
      }
      percent = pct
    }
    if (mode === 'invoice_amount') {
      const amt = parseFloat(amountInput)
      if (isNaN(amt) || amt <= 0) {
        toast.error(t('invoiceCard.invalidAmount'))
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
          toast.success(t('invoiceCard.created'))
          // A created invoice can still carry warnings (e.g. the workshop
          // PDF attachment failed); each one is the user's to act on.
          response.messages?.forEach((message) => toast.warning(message))
          afterInvoiceChange()
        },
        onError: (error) => {
          toast.error(
            t('invoiceCard.createFailed', {
              reason: apiErrorMessage(error, t('invoiceCard.createFailedFallback')),
            }),
          )
        },
      },
    )
  }

  const executeDelete = (invoice: { xero_id: string; number: string }, voidApproved: boolean) => {
    if (deleteInvoice.isPending) return
    setVoidOffer(null)
    deleteInvoice.mutate(
      {
        path: { job_id: jobId },
        query: { xero_invoice_id: invoice.xero_id, void_approved: voidApproved },
      },
      {
        onSuccess: (response) => {
          toast.success(response.message ?? t('invoiceCard.deleted'))
          afterInvoiceChange()
        },
        onError: (error) => {
          const reason = apiErrorMessage(error, t('invoiceCard.deleteFailed'))
          if (apiErrorType(error) === 'invoice_approved') {
            setVoidOffer({ xeroId: invoice.xero_id, number: invoice.number, reason })
            return
          }
          toast.error(reason)
        },
      },
    )
  }

  return (
    <aside className="rounded-xl border border-slate-200 bg-white">
      <div className="px-3 pt-3 pb-2">
        <h3 className="text-base font-semibold text-gray-900">
          {t('invoiceCard.title')}{' '}
          <span className="text-sm text-slate-400">({invoices.length})</span>
        </h3>
        <p className="text-xs text-slate-500">{t('invoiceCard.subtitle')}</p>
      </div>

      <div className="max-h-[20rem] overflow-y-auto px-2 pb-2">
        {invoicesQuery.isError ? (
          // A failed read must not masquerade as the empty state: "No
          // invoices" tells staff it is safe to invoice again.
          <div className="py-6 text-center text-red-700">{t('invoiceCard.loadFailed')}</div>
        ) : invoices.length === 0 ? (
          <div className="py-6 text-center text-gray-500">{t('invoiceCard.empty')}</div>
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
                      {xeroInvoiceStatusLabel(invoice.status)}
                    </span>
                  </div>
                  <div className="text-[11px] leading-4 text-slate-500">
                    {formatDate(invoice.date)}
                  </div>
                </div>

                <div className="shrink-0 text-sm font-semibold tabular-nums text-slate-900">
                  {t('invoiceCard.amountExclGst', {
                    amount: formatCurrency(invoice.total_excl_tax),
                  })}
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    data-automation-id={`JobInvoiceCard-open-${invoice.id}`}
                    aria-label={t('invoiceCard.openInXero', { number: invoice.number })}
                    disabled={!invoice.online_url}
                    onClick={() => {
                      if (invoice.online_url) {
                        // noopener: the Xero tab must not get a handle on
                        // this window (reverse tabnabbing).
                        window.open(invoice.online_url, '_blank', 'noopener,noreferrer')
                      } else {
                        toast.error(t('invoiceCard.noOnlineUrl'))
                      }
                    }}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="destructive"
                    size="icon-sm"
                    data-automation-id={`JobInvoiceCard-delete-${invoice.id}`}
                    aria-label={t('invoiceCard.delete', { number: invoice.number })}
                    title={
                      invoice.status === 'VOIDED'
                        ? t('invoiceCard.titles.deleteVoided')
                        : t('invoiceCard.titles.delete')
                    }
                    disabled={deleteInvoice.isPending || invoice.status === 'VOIDED'}
                    onClick={() => executeDelete(invoice, false)}
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
            title={t('invoiceCard.titles.create')}
            disabled={createInvoice.isPending || paid || !xeroConnected}
            className="flex items-center gap-2 rounded-md bg-orange-600 px-4 py-2 text-white hover:bg-orange-700 focus:ring-2 focus:ring-orange-500 focus:outline-none disabled:opacity-50"
            onClick={openModal}
          >
            {createInvoice.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {createInvoice.isPending
              ? t('invoiceCard.creating')
              : xeroConnected
                ? t('invoiceCard.create')
                : t('invoiceCard.loginFirst')}
          </button>
        ) : (
          <p
            data-automation-id="JobFinishTab-fully-invoiced"
            className="text-center text-xs text-slate-500"
          >
            {t('invoiceCard.fullyInvoiced')}
          </p>
        )}

        {paid && (
          <p className="text-center text-xs text-slate-500">
            <Trans t={t} i18nKey="invoiceCard.paidHint" components={{ strong: <strong /> }} />
          </p>
        )}
      </div>

      <Dialog
        open={voidOffer !== null}
        onOpenChange={(open) => {
          if (!open) setVoidOffer(null)
        }}
      >
        <DialogContent className="sm:max-w-md" data-automation-id="JobInvoiceCard-void-offer">
          <DialogHeader>
            <DialogTitle>
              {t('invoiceCard.voidDialog.title', { number: voidOffer?.number ?? '' })}
            </DialogTitle>
            <DialogDescription>{voidOffer?.reason}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setVoidOffer(null)}>
              {t('invoiceCard.cancel')}
            </Button>
            <Button
              variant="outline"
              data-automation-id="JobInvoiceCard-void-offer-second-invoice"
              title={secondInvoiceBlocked ?? t('invoiceCard.titles.create')}
              disabled={secondInvoiceBlocked !== null}
              onClick={() => {
                setVoidOffer(null)
                openModal()
              }}
            >
              {t('invoiceCard.voidDialog.secondInvoice')}
            </Button>
            <Button
              variant="destructive"
              data-automation-id="JobInvoiceCard-void-offer-void"
              onClick={() => {
                if (voidOffer !== null) {
                  executeDelete({ xero_id: voidOffer.xeroId, number: voidOffer.number }, true)
                }
              }}
            >
              {t('invoiceCard.voidDialog.void')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('invoiceCard.dialogTitle')}</DialogTitle>
            <DialogDescription>{modalDescription}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-1 rounded-lg bg-slate-50 p-3 text-sm">
              <div className="flex justify-between border-t pt-1">
                <span
                  className="font-medium text-slate-700"
                  title={t('invoiceCard.titles.currentAmount')}
                >
                  {t('invoiceCard.currentAmount')}
                </span>
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
                    title={t('invoiceCard.titles.fullInvoice')}
                    disabled={createInvoice.isPending}
                    onClick={() => executeCreate('invoice_full')}
                  >
                    <span className="font-semibold">{fullInvoiceLabel}</span>
                    <span className="text-xs font-normal opacity-90">
                      {t('invoiceCard.amountExclGst', {
                        amount: formatCurrency(remainingToInvoice),
                      })}
                    </span>
                  </Button>

                  <Button
                    variant="outline"
                    className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
                    data-automation-id="JobFinishTab-mode-invoice-percent"
                    title={t('invoiceCard.titles.percentMode')}
                    disabled={createInvoice.isPending}
                    onClick={() => selectMode('invoice_percent')}
                  >
                    <span className="font-semibold">{t('invoiceCard.percentMode')}</span>
                    <span className="text-xs font-normal opacity-70">
                      {t('invoiceCard.percentModeHint')}
                    </span>
                  </Button>
                  {selectedMode === 'invoice_percent' && (
                    <div className="flex gap-2">
                      <input
                        type="number"
                        min="1"
                        max="100"
                        step="0.1"
                        aria-label={t('invoiceCard.percentInput')}
                        placeholder={t('invoiceCard.percentPlaceholder')}
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
                        {t('invoiceCard.confirm')}
                      </Button>
                    </div>
                  )}
                </>
              ) : (
                <Button
                  className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
                  data-automation-id="JobFinishTab-mode-invoice-costs-to-date"
                  title={t('invoiceCard.titles.costsToDate')}
                  disabled={createInvoice.isPending}
                  onClick={() => executeCreate('invoice_costs_to_date')}
                >
                  <span className="font-semibold">{costsToDateLabel}</span>
                  <span className="text-xs font-normal opacity-90">
                    {t('invoiceCard.amountExclGst', { amount: formatCurrency(remainingToInvoice) })}
                  </span>
                </Button>
              )}

              <Button
                variant="outline"
                className="flex h-auto w-full flex-col items-start gap-1 px-4 py-4"
                data-automation-id="JobFinishTab-mode-invoice-amount"
                title={t('invoiceCard.titles.amountMode')}
                disabled={createInvoice.isPending}
                onClick={() => selectMode('invoice_amount')}
              >
                <span className="font-semibold">{t('invoiceCard.amountMode')}</span>
                <span className="text-xs font-normal opacity-70">{customAmountHint}</span>
              </Button>
              {selectedMode === 'invoice_amount' && (
                <div className="flex gap-2">
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    aria-label={t('invoiceCard.amountInput')}
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
                    {t('invoiceCard.confirm')}
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
              {t('invoiceCard.cancel')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  )
}
