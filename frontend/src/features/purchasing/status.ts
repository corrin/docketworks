import type { PurchaseOrderList } from '@/api'
import { i18n } from '@/lib/i18n'

/** The five states the API can send, straight off the wire contract. */
export type PoStatus = PurchaseOrderList['status']

/**
 * The one description of a purchase-order status: its label's catalogue key
 * and its badge colour.
 *
 * Opus: `Record<PoStatus, …>` is what makes this exhaustive — a sixth status
 * added to the API fails to compile here rather than rendering a grey badge and
 * a raw snake_case label. Two separate lists, the select's options and the list
 * screen's colours, would drift the moment one gained a state (ADR 0039).
 */
export const PO_STATUS_DISPLAY: Record<PoStatus, { labelKey: string; className: string }> = {
  draft: { labelKey: 'draft', className: 'bg-gray-100 text-gray-700' },
  submitted: { labelKey: 'submitted', className: 'bg-blue-100 text-blue-800' },
  partially_received: { labelKey: 'partiallyReceived', className: 'bg-amber-100 text-amber-800' },
  fully_received: { labelKey: 'fullyReceived', className: 'bg-green-100 text-green-800' },
  deleted: { labelKey: 'deleted', className: 'bg-red-100 text-red-800' },
}

/** A status in words, read from the catalogue when rendered (ADR 0069). */
export function poStatusLabel(status: PoStatus): string {
  return i18n.t(`purchasing:status.${PO_STATUS_DISPLAY[status].labelKey}`)
}

/** What a status means, for its select option's tooltip (ADR 0068). */
export function poStatusTitle(status: PoStatus): string {
  return i18n.t(`purchasing:poSummary.statusTitles.${PO_STATUS_DISPLAY[status].labelKey}`)
}

/**
 * Select options, in the order a purchase order moves through them.
 *
 * Opus: written out rather than derived from Object.keys, which returns
 * string[] and needs an assertion to narrow. `satisfies` proves every entry is
 * a real status without one, and the Record above proves none is missing.
 */
export const PO_STATUS_ORDER = [
  'draft',
  'submitted',
  'partially_received',
  'fully_received',
  'deleted',
] as const satisfies readonly PoStatus[]

/**
 * Narrow a Radix select's `string` callback value to the wire union.
 *
 * Opus: throws rather than falling back, the same shape as
 * SmartTimesheetTable's rateMultiplier. The only values reaching it are the
 * PO_STATUS_ORDER values rendered into the select, so an unknown one means the
 * options and the wire contract have diverged — which must surface, not resolve
 * to a default that silently PATCHes the wrong status.
 */
export function toPoStatus(value: string): PoStatus {
  const match = PO_STATUS_ORDER.find((status) => status === value)
  if (match === undefined) throw new Error(`Unknown purchase order status ${value}`)
  return match
}
