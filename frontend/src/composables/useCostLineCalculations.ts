/**
 * useCostLineCalculations - Centralizes all calculation rules for CostLine editing in the UI
 *
 * IMPORTANT:
 * - This composable ONLY deals with presentation-level calculations for UX.
 * - It never creates or exports backend data types; it uses generated schemas exclusively.
 * - It must not enforce backend logic; the backend remains the source of truth.
 * - UI override flags are tracked locally (non-persistent) using WeakMaps.
 *
 * Responsibilities:
 * - Compute unit_cost and unit_rev according to the line kind (material, time, adjust).
 * - For time: unit_cost from Company Defaults wage_rate; unit_rev from the job's
 *   per-labour-subtype charge-out rate (rates are per job + labour subtype, not
 *   company-wide). The charge-out resolver is mandatory — there is no company
 *   default to fall back to.
 * - For material (and adjustment by design), default unit_rev uses materials_markup when not overridden.
 * - Maintain local "unit_rev overridden" state so that recalculation does not override user's explicit values,
 *   until the kind or selected item changes.
 * - Compute totals (total_cost = quantity * unit_cost, total_rev = quantity * unit_rev) with proper rounding.
 * - Provide validation helpers (quantity constraints by kind).
 *
 * NOTE ON OVERRIDES:
 * - We track "unit_rev overridden" status in a WeakSet/WeakMap, so we do not mutate backend types and do not persist UI flags.
 * - When user manually edits unit_rev, call markUnitRevOverridden(line, true).
 * - When kind changes or item changes, call resetUnitRevOverride(line) so default calculation can apply again.
 */

import { computed } from 'vue'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'
import { requiredNumber } from '@/utils/requiredNumber'

type CostLine = z.infer<typeof schemas.CostLine>
type CompanyDefaults = z.infer<typeof schemas.CompanyDefaults>

// Local UI-only override tracking (not persisted)
// - unitRevOverride: has user manually overridden unit_rev?
const unitRevOverride = new WeakSet<CostLine>()

export interface LineDerivedValues {
  unit_cost: number
  unit_rev: number
  total_cost: number
  total_rev: number
}

export interface ValidationIssue {
  field: 'quantity' | 'unit_cost' | 'unit_rev' | 'desc' | 'kind'
  message: string
}

export interface ValidationResult {
  isValid: boolean
  issues: ValidationIssue[]
}

export interface ApplyResult {
  derived: LineDerivedValues
  // Whether we applied default calculation for unit_rev (no override)
  usedDefaultRevenue: boolean
}

/**
 * Public API of the composable
 */
export function useCostLineCalculations(options: {
  getCompanyDefaults?: () => CompanyDefaults | null
  /**
   * Resolves the charge-out rate for a time line from the job's per-subtype
   * labour rates (looked up by line.labour_subtype, workshop fallback).
   * Required: every job carries its own per-subtype rate via job labour_rates,
   * so there is no company-wide default to fall back to (ADR 0015). A caller
   * that cannot supply this is a contract violation, not a default case.
   */
  getTimeChargeOutRate: (line: CostLine) => number | null
  // Monetary rounding scale, defaults to 2 decimals for currency
  moneyScale?: number
  // Quantity scale, defaults to 3 decimals for better time precision (optional)
  quantityScale?: number
}) {
  const getDefaults = options.getCompanyDefaults ?? (() => null)
  const getTimeChargeOutRate = options.getTimeChargeOutRate
  if (!getTimeChargeOutRate) {
    // Contract violation, not a recoverable default: time charge-out rates are
    // per job + labour subtype (job labour_rates). There is no company-wide
    // rate to fall back to (ADR 0015 — fix the caller, don't soften here).
    throw new Error(
      'useCostLineCalculations requires getTimeChargeOutRate; time charge-out rates are per job/subtype, not a company default.',
    )
  }
  const moneyScale = options.moneyScale ?? 2
  const quantityScale = options.quantityScale ?? 3

  const companyDefaults = computed(() => getDefaults())

  /**
   * Mark or unmark that the user explicitly overrode unit_rev for this line.
   * When true, subsequent automatic recalculations should not replace unit_rev
   * until we explicitly reset (e.g., when the item or kind changes).
   */
  function markUnitRevOverridden(line: CostLine, overridden: boolean) {
    if (overridden) unitRevOverride.add(line)
    else unitRevOverride.delete(line)
  }

  function isUnitRevOverridden(line: CostLine): boolean {
    return unitRevOverride.has(line)
  }

  /**
   * Reset override state (e.g., after item selection or kind change).
   */
  function resetUnitRevOverride(line: CostLine) {
    unitRevOverride.delete(line)
  }

  function transferUnitRevOverride(from: CostLine, to: CostLine) {
    if (unitRevOverride.has(from)) unitRevOverride.add(to)
    else unitRevOverride.delete(to)
  }

  /**
   * Format helpers (rounding with fixed decimals)
   */
  function roundMoney(v: unknown, label: string): number {
    return roundTo(requiredNumber(v, label), moneyScale)
  }

  function roundQty(v: unknown, label: string): number {
    return roundTo(requiredNumber(v, label), quantityScale)
  }

  function roundTo(value: number, scale: number): number {
    const factor = Math.pow(10, scale)
    return Math.round(value * factor) / factor
  }

  /**
   * Default calculation for material/adjustment revenue:
   * unit_rev = unit_cost * (1 + materials_markup)
   */
  function calcMaterialRevenue(
    unit_cost: number,
    materials_markup: number | undefined | null,
  ): number {
    const markup = requiredNumber(materials_markup, 'company defaults materials_markup')
    return roundMoney(unit_cost * (1 + markup), 'calculated material unit_rev')
  }

  /**
   * Compute unit_cost and unit_rev according to line.kind and Company Defaults.
   * - time: unit_cost = wage_rate, unit_rev = job rate for the line's labour subtype
   * - material: unit_cost editable; unit_rev default uses markup unless overridden
   * - adjust: unit_cost and unit_rev editable; default unit_rev uses markup unless overridden
   */
  function computeUnits(line: CostLine): {
    unit_cost: number
    unit_rev: number
    usedDefaultRevenue: boolean
  } {
    const defaults = companyDefaults.value
    const kind = String(line.kind)

    if (kind === 'time') {
      const wage = roundMoney(defaults?.wage_rate, 'company defaults wage_rate')
      // Per-subtype job rate (job labour_rates). There is no company-wide
      // charge-out rate — the resolver is mandatory (enforced at construction).
      const charge = roundMoney(getTimeChargeOutRate(line), 'time charge_out_rate')
      return { unit_cost: wage, unit_rev: charge, usedDefaultRevenue: true }
    }

    // For material and adjustment, use provided unit_cost; default unit_rev = cost * (1 + materials_markup)
    const baseCost = roundMoney(line.unit_cost, 'cost line unit_cost')

    if (kind === 'material' || kind === 'adjust') {
      if (isUnitRevOverridden(line)) {
        // Respect manual override; do not change unit_rev here
        return {
          unit_cost: baseCost,
          unit_rev: roundMoney(line.unit_rev, 'cost line unit_rev'),
          usedDefaultRevenue: false,
        }
      }

      const defaultRev = calcMaterialRevenue(baseCost, defaults?.materials_markup)
      return {
        unit_cost: baseCost,
        unit_rev: defaultRev,
        usedDefaultRevenue: true,
      }
    }

    // Fallback: keep existing numbers (defensive, though kinds are limited)
    return {
      unit_cost: roundMoney(line.unit_cost, 'cost line unit_cost'),
      unit_rev: roundMoney(line.unit_rev, 'cost line unit_rev'),
      usedDefaultRevenue: false,
    }
  }

  /**
   * Compute totals based on quantity and the resolved unit costs.
   */
  function computeTotals(
    quantity: number,
    unit_cost: number,
    unit_rev: number,
  ): {
    total_cost: number
    total_rev: number
  } {
    const qty = roundQty(quantity, 'cost line quantity')
    return {
      total_cost: roundMoney(qty * unit_cost, 'calculated total_cost'),
      total_rev: roundMoney(qty * unit_rev, 'calculated total_rev'),
    }
  }

  /**
   * Validate line according to UX rules:
   * - material/time: quantity must be > 0
   * - adjustment: quantity can be zero or negative
   * - Prevent edits for locked fields is handled at the UI level (not here)
   */
  function validateLine(line: CostLine): ValidationResult {
    const issues: ValidationIssue[] = []
    const kind = String(line.kind)
    let qty: number
    try {
      qty = requiredNumber(line.quantity, 'cost line quantity')
    } catch {
      issues.push({ field: 'quantity', message: 'Quantity must be a valid number.' })
      return { isValid: false, issues }
    }

    if (kind === 'material' || kind === 'time') {
      if (!(qty > 0)) {
        issues.push({ field: 'quantity', message: 'Quantity must be greater than zero.' })
      }
    } else if (kind === 'adjust') {
      // zero or negative allowed - no validation error here
    }

    return { isValid: issues.length === 0, issues }
  }

  /**
   * Apply the calculation pipeline to produce derived values for the UI.
   * This DOES NOT mutate the line (pure compute) and can be called after any edit.
   */
  function apply(line: CostLine): ApplyResult {
    const units = computeUnits(line)
    const qty = requiredNumber(line.quantity, 'cost line quantity')
    const totals = computeTotals(qty, units.unit_cost, units.unit_rev)
    return {
      derived: {
        unit_cost: units.unit_cost,
        unit_rev: units.unit_rev,
        total_cost: totals.total_cost,
        total_rev: totals.total_rev,
      },
      usedDefaultRevenue: units.usedDefaultRevenue,
    }
  }

  /**
   * Handle user-driven changes to specific fields.
   * - When kind changes: reset unit_rev override to allow defaulting again.
   * - When item selection changes: reset unit_rev override to recalc with markup.
   * - When unit_rev changes manually: mark overridden so we preserve user intent.
   */
  function onKindChanged(line: CostLine) {
    resetUnitRevOverride(line)
  }

  function onItemSelected(line: CostLine) {
    resetUnitRevOverride(line)
  }

  function onUnitRevenueManuallyEdited(line: CostLine) {
    markUnitRevOverridden(line, true)
  }

  /**
   * Utility helpers to know if certain fields should be editable (UI decision).
   * This is provided for convenience to keep logic centralized.
   */
  function isUnitCostEditable(line: CostLine): boolean {
    return String(line.kind) !== 'time'
  }

  function isUnitRevenueEditable(line: CostLine): boolean {
    // For "time" both unit_cost and unit_rev are read-only by UX spec
    return String(line.kind) !== 'time'
  }

  return {
    // State
    companyDefaults,

    // Override management (UI only)
    markUnitRevOverridden,
    isUnitRevOverridden,
    resetUnitRevOverride,
    transferUnitRevOverride,

    // Calculations
    apply,
    computeUnits,
    computeTotals,
    calcMaterialRevenue,

    // Validation
    validateLine,

    // Change handlers
    onKindChanged,
    onItemSelected,
    onUnitRevenueManuallyEdited,

    // UI capability helpers
    isUnitCostEditable,
    isUnitRevenueEditable,

    // Rounding helpers (exported for custom cells if needed)
    roundMoney,
    roundQty,
    roundTo,
  }
}
