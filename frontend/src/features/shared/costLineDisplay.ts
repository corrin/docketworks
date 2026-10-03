import type { CostLineOut, CostLineUpdateRequest } from '@/api'

/**
 * What a cost-line PATCH shows in the cache before its echo. The wire accepts
 * number|string for decimals while CostLineOut carries strings; the echo and
 * the settle refetch replace the approximation with canonical values.
 */
export function costLineDisplay(body: CostLineUpdateRequest): Partial<CostLineOut> {
  const display: Partial<CostLineOut> = {}
  if (body.desc !== undefined) display.desc = body.desc
  if (body.kind !== undefined) display.kind = body.kind
  if (body.labour_subtype !== undefined) display.labour_subtype = body.labour_subtype
  if (body.quantity !== undefined) display.quantity = String(body.quantity)
  if (body.unit_cost !== undefined) display.unit_cost = String(body.unit_cost)
  if (body.unit_rev !== undefined) display.unit_rev = String(body.unit_rev)
  if (body.ext_refs !== undefined) display.ext_refs = body.ext_refs
  if (body.meta !== undefined) display.meta = body.meta
  return display
}
