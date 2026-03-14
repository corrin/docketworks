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
 * - Apply Company Defaults for time (wage_rate/charge_out_rate).
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
export function useCostLineCalculations(options?: {
  getCompanyDefaults?: () => CompanyDefaults | null
  // Monetary rounding scale, defaults to 2 decimals for currency
  moneyScale?: number
  // Quantity scale, defaults to 3 decimals for better time precision (optional)
  quantityScale?: number
}) {
  const getDefaults = options?.getCompanyDefaults ?? (() => null)
  const moneyScale = options?.moneyScale ?? 2
  const quantityScale = options?.quantityScale ?? 3

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

  /**
   * Format helpers (rounding with fixed decimals)
   */
  function roundMoney(v: number | undefined | null): number {
    const n = Number(v ?? 0)
    return roundTo(n, moneyScale)
  }

  function roundQty(v: number | undefined | null): number {
    const n = Number(v ?? 0)
    return roundTo(n, quantityScale)
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
    const markup = Number(materials_markup ?? 0)
    return roundMoney(unit_cost * (1 + markup))
  }

  /**
   * Compute unit_cost and unit_rev according to line.kind and Company Defaults.
   * - time: unit_cost = wage_rate, unit_rev = charge_out_rate (both read-only by UX)
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
      const wage = roundMoney(defaults?.wage_rate ?? 0)
      const charge = roundMoney(defaults?.charge_out_rate ?? 0)
      return { unit_cost: wage, unit_rev: charge, usedDefaultRevenue: true }
    }

    // For material and adjustment, use provided unit_cost; default unit_rev = cost * (1 + materials_markup)
    const baseCost = roundMoney(line.unit_cost ?? 0)

    if (kind === 'material' || kind === 'adjust') {
      if (isUnitRevOverridden(line)) {
        // Respect manual override; do not change unit_rev here
        return {
          unit_cost: baseCost,
          unit_rev: roundMoney(line.unit_rev ?? 0),
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
      unit_cost: roundMoney(line.unit_cost ?? 0),
      unit_rev: roundMoney(line.unit_rev ?? 0),
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
    const qty = roundQty(quantity)
    return {
      total_cost: roundMoney(qty * unit_cost),
      total_rev: roundMoney(qty * unit_rev),
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
    const qty = Number(line.quantity ?? 0)

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
    const qty = Number(line.quantity ?? 0)
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

  function isItemSelectionEnabled(line: CostLine): boolean {
    const kind = String(line.kind)
    if (kind === 'time') return false
    // material and adjustment: enabled
    return true
  }

  return {
    // State
    companyDefaults,

    // Override management (UI only)
    markUnitRevOverridden,
    isUnitRevOverridden,
    resetUnitRevOverride,

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
    isItemSelectionEnabled,

    // Rounding helpers (exported for custom cells if needed)
    roundMoney,
    roundQty,
    roundTo,
  }
}
