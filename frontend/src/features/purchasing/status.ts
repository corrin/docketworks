import type { PurchaseOrderList } from '@/api'

/** The five states the API can send, straight off the wire contract. */
export type PoStatus = PurchaseOrderList['status']

/**
 * The one description of a purchase-order status: its label and its badge
 * colour.
 *
 * Opus: `Record<PoStatus, …>` is what makes this exhaustive — a sixth status
 * added to the API fails to compile here rather than rendering a grey badge and
 * a raw snake_case label. Two separate lists, the select's options and the list
 * screen's colours, would drift the moment one gained a state (ADR 0039).
 */
export const PO_STATUS_DISPLAY: Record<PoStatus, { label: string; className: string }> = {
  draft: { label: 'Draft', className: 'bg-gray-100 text-gray-700' },
  submitted: { label: 'Submitted to Supplier', className: 'bg-blue-100 text-blue-800' },
  partially_received: { label: 'Partially Received', className: 'bg-amber-100 text-amber-800' },
  fully_received: { label: 'Fully Received', className: 'bg-green-100 text-green-800' },
  deleted: { label: 'Deleted', className: 'bg-red-100 text-red-800' },
}

/**
 * Select options, in the order a purchase order moves through them.
 *
 * Opus: written out rather than derived from Object.keys, which returns
 * string[] and needs an assertion to narrow. `satisfies` proves every entry is
 * a real status without one, and the Record above proves none is missing.
 */
const PO_STATUS_ORDER = [
  'draft',
  'submitted',
  'partially_received',
  'fully_received',
  'deleted',
] as const satisfies readonly PoStatus[]

export const PO_STATUS_OPTIONS: readonly { value: PoStatus; label: string }[] = PO_STATUS_ORDER.map(
  (value) => ({ value, label: PO_STATUS_DISPLAY[value].label }),
)

/**
 * Narrow a Radix select's `string` callback value to the wire union.
 *
 * Opus: throws rather than falling back, the same shape as
 * SmartTimesheetTable's rateMultiplier. The only values reaching it are the
 * PO_STATUS_OPTIONS rendered into the select, so an unknown one means the
 * options and the wire contract have diverged — which must surface, not resolve
 * to a default that silently PATCHes the wrong status.
 */
export function toPoStatus(value: string): PoStatus {
  const match = PO_STATUS_ORDER.find((status) => status === value)
  if (match === undefined) throw new Error(`Unknown purchase order status ${value}`)
  return match
}
