import { i18n } from '@/lib/i18n'

/** Xero's invoice statuses (accounting InvoiceStatus). */
const XERO_INVOICE_STATUSES = [
  'DRAFT',
  'SUBMITTED',
  'AUTHORISED',
  'PAID',
  'VOIDED',
  'DELETED',
] as const

/** An invoice status in Xero's own screen words ("Awaiting Payment", not
    AUTHORISED). Throws on a status InvoiceStatus does not declare: the wire
    types it as a plain string. */
export function xeroInvoiceStatusLabel(status: string): string {
  const known = XERO_INVOICE_STATUSES.find((candidate) => candidate === status)
  if (known === undefined) {
    throw new Error(`Unknown Xero invoice status: '${status}'`)
  }
  return i18n.t(`job:invoiceCard.status.${known}`)
}

/** A voided or deleted invoice is no longer owed: shown, but counted nowhere. */
export function isRemovedInvoiceStatus(status: string): boolean {
  return status === 'VOIDED' || status === 'DELETED'
}
