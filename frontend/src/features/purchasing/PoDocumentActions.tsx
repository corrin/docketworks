import { useMutation } from '@tanstack/react-query'
import { Mail, Printer } from 'lucide-react'
import { toast } from 'sonner'

import { apiErrorMessage, getPurchaseOrderEmailMutation } from '@/api'
import type { PurchaseOrderDetail } from '@/api'
import { Button } from '@/components/ui/button'
import { printPurchaseOrder } from './print'

interface PoDocumentActionsProps {
  po: PurchaseOrderDetail
}

/**
 * Sending the order to the supplier: print it, or draft an email with it.
 *
 * The email is a Gmail draft in the operator's own mailbox with the order PDF
 * attached, not a mailto: link. mailto cannot carry an attachment, so the old
 * one composed a message saying "please find attached" and attached nothing.
 *
 * There is deliberately no "sync with Xero" button beside these. Xero holds a
 * copy so the supplier's bill has something to reconcile against, and keeping
 * that copy current is the system's job — a button would make it an operator's
 * to remember, and forgetting is invisible until the accounts disagree.
 */
export function PoDocumentActions({ po }: PoDocumentActionsProps) {
  const composeEmail = useMutation(getPurchaseOrderEmailMutation())

  const emailSupplier = () => {
    composeEmail.mutate(
      { path: { po_id: po.id }, body: {} },
      {
        onSuccess: (email) => {
          // The server drafts the message in this operator's own mailbox with
          // the order PDF attached, and hands back where to open it. Nothing is
          // sent: they read it and send it themselves.
          toast.success(email.message ?? 'Draft created')
          window.open(email.draft_url, '_blank', 'noopener,noreferrer')
        },
        onError: (error) =>
          toast.error(apiErrorMessage(error, 'Failed to draft the supplier email.')),
      },
    )
  }

  return (
    <div className="flex gap-2">
      <Button
        variant="outline"
        data-automation-id="PoDetailView-print"
        onClick={() => void printPurchaseOrder(po.id)}
      >
        <Printer className="mr-2 h-4 w-4" />
        Print
      </Button>
      <Button
        variant="outline"
        // Disabled with a reason rather than failing on click: the composer
        // refuses a supplier with no address, and a button that cannot work
        // should say so before it is pressed, as the Xero card does.
        disabled={composeEmail.isPending || !po.supplier_has_email}
        title={po.supplier_has_email ? undefined : 'This supplier has no email address on file'}
        data-automation-id="PoDetailView-email"
        onClick={emailSupplier}
      >
        <Mail className="mr-2 h-4 w-4" />
        {composeEmail.isPending ? 'Drafting…' : 'Email supplier'}
      </Button>
    </div>
  )
}
