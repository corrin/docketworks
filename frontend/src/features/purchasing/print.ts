import { getPurchaseOrderPdf } from '@/api'
import { openBlobInNewTab } from '@/features/job/open-blob'

/**
 * Open the supplier's copy of a purchase order for printing.
 *
 * The PDF is what the supplier receives, so it is worth knowing what it does
 * and does not carry: item code, description and quantity, and no prices or
 * total (`purchase_order_pdf_service`). Changing that is a decision about what
 * we tell suppliers, not a rendering detail.
 */
export async function printPurchaseOrder(poId: string): Promise<void> {
  await openBlobInNewTab(
    async () =>
      (
        await getPurchaseOrderPdf({
          path: { po_id: poId },
          responseType: 'blob',
          throwOnError: true,
        })
      ).data,
    'purchase order PDF',
    { print: true },
  )
}
