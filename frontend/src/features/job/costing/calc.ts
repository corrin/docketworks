/**
 * Pure cost-line derivations. No React, no transport: everything here is a
 * plain function from wire types to wire types, unit-tested in isolation.
 *
 * These produce editable *defaults* the server then stores verbatim — they
 * are business input rules (v1 parity), not display math, so ADR 0046's
 * "never recompute money for display" rule is not in play.
 */

import type { CostLineOut, CostLineUpdateRequest, JobLabourRateOut, StockItem } from '@/api'
import type { DraftLine } from './types'

/** Default revenue for a material/adjustment line: cost marked up, 2 dp. */
export function derivedUnitRev(unitCost: string, materialsMarkup: string): string {
  return (Number(unitCost) * (1 + Number(materialsMarkup))).toFixed(2)
}

/**
 * The PATCH for binding a stock item to a line. ext_refs is merged, never
 * replaced: the backend stores the patch's ext_refs wholesale, so omitting an
 * existing key would silently drop it.
 */
export function stockPickPatch(
  line: CostLineOut,
  stock: StockItem,
  materialsMarkup: string,
): CostLineUpdateRequest {
  return {
    kind: 'material',
    desc: stock.description,
    unit_cost: stock.unit_cost,
    unit_rev: stock.unit_revenue ?? derivedUnitRev(stock.unit_cost, materialsMarkup),
    // Cleared, not omitted: converting a time line to material must not
    // leave its stale subtype behind (validation only checks time lines).
    labour_subtype: null,
    ext_refs: { ...line.ext_refs, stock_id: stock.id },
  }
}

/**
 * The PATCH for binding a labour rate: the line becomes time, costed at the
 * company wage rate and charged at the job's rate for that subtype, and any
 * stock binding is dropped.
 */
export function labourPickPatch(
  line: CostLineOut,
  {
    rate,
    wageRate,
    allRates,
  }: { rate: JobLabourRateOut; wageRate: string; allRates: readonly JobLabourRateOut[] },
): CostLineUpdateRequest {
  const { stock_id: _dropped, ...keptRefs } = line.ext_refs
  return {
    kind: 'time',
    labour_subtype: rate.labour_subtype,
    desc: labourPickDesc(line.desc, rate, allRates),
    unit_cost: wageRate,
    unit_rev: rate.charge_out_rate,
    ext_refs: keptRefs,
  }
}

/**
 * A labour pick keeps a user-authored description (v1 rule): only blank,
 * the generic 'Labour', or another subtype's auto-fill are replaced with
 * the picked subtype's name.
 */
export function labourPickDesc(
  currentDesc: string | null,
  rate: JobLabourRateOut,
  allRates: readonly JobLabourRateOut[],
): string {
  const trimmed = (currentDesc ?? '').trim()
  const isAutoFill =
    trimmed === '' ||
    trimmed === 'Labour' ||
    allRates.some((candidate) => candidate.labour_subtype_name === trimmed)
  return isAutoFill ? rate.labour_subtype_name : trimmed
}

/**
 * The item trigger's accessible name. 'Select Item' only when nothing is
 * bound — the E2E repair loop counts buttons by that exact name and must stop
 * matching a row once it is repaired.
 */
export function itemLabel(
  line: CostLineOut,
  stockById: ReadonlyMap<string, StockItem>,
  labourRates: readonly JobLabourRateOut[],
): string {
  if (line.kind === 'time' && line.labour_subtype !== null) {
    const rate = labourRates.find((candidate) => candidate.labour_subtype === line.labour_subtype)
    if (rate) return rate.labour_subtype_name
    return line.labour_subtype
  }
  const stockId = line.ext_refs['stock_id']
  if (typeof stockId === 'string') {
    const stock = stockById.get(stockId)
    if (stock) return stock.item_code ?? stock.description
    // Bound to stock the picker page has not loaded — still not 'Select Item'.
    return 'Stock item'
  }
  return 'Select Item'
}

/** A receipt allocation's quantity IS the received quantity of a PO line, so
 * the costing grid must not edit any of it (v1 rule) — reconciliation
 * belongs on the purchasing side. */
export function isDeliveryReceiptLine(line: CostLineOut): boolean {
  return line.meta['source'] === 'delivery_receipt'
}

/** A draft may POST only when every required field is present and sane.
 * unit_rev is NOT required: an untouched revenue derives from the cost at
 * POST time. Deriving it into the draft state on the cost commit instead
 * flips the controlled unit-rev input mid-edit and loses a concurrent
 * override (caught by the cost-entry E2E). */
export function isDraftReadyToPersist(draft: DraftLine): boolean {
  if (!draft.desc.trim()) return false
  const quantity = Number(draft.quantity)
  if (!Number.isFinite(quantity) || quantity <= 0) return false
  return draft.unit_cost !== null
}
