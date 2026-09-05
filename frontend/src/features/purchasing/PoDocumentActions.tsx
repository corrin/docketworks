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
 * Sending the order to the supplier: print it, or mail it.
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
          // The server composes subject and body from the order and returns the
          // mailto URL; opening it hands the draft to whatever the operator
          // actually uses for mail. Nothing is sent from here.
          if (!email.mailto_url) {
            toast.error(email.message ?? 'No email address for this supplier.')
            return
          }
          window.open(email.mailto_url, '_blank', 'noopener,noreferrer')
        },
        onError: (error) =>
          toast.error(apiErrorMessage(error, 'Failed to compose the supplier email.')),
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
        disabled={composeEmail.isPending || !po.supplier_id}
        data-automation-id="PoDetailView-email"
        onClick={emailSupplier}
      >
        <Mail className="mr-2 h-4 w-4" />
        {composeEmail.isPending ? 'Preparing…' : 'Email supplier'}
      </Button>
    </div>
  )
}
