/**
 * Pure calculation helpers for timesheet entries.
 *
 * Backend types use snake_case (`quantity`, `unit_cost`, `total_cost`) and the
 * rate multiplier lives in `meta.wage_rate_multiplier`. These helpers operate
 * directly on the wire shape so SmartTimesheetTable can render derived columns
 * (Wage, Bill) without inventing camelCase aliases.
 */

import type { z } from 'zod'
import type { schemas } from '../api/generated/api'

export type TimesheetCostLine = z.infer<typeof schemas.TimesheetCostLine>

export function getRateMultiplier(rateType: string): number {
  switch (rateType) {
    case '1.5':
      return 1.5
    case '2.0':
      return 2.0
    case 'Unpaid':
      return 0.0
    default:
      return 1.0
  }
}

export function getRateTypeFromMultiplier(m: number | undefined | null): string {
  if (m === 1.5) return '1.5'
  if (m === 2.0) return '2.0'
  if (m === 0.0) return 'Unpaid'
  return 'Ord'
}

export function getMeta(entry: TimesheetCostLine): Record<string, unknown> {
  return (entry.meta ?? {}) as Record<string, unknown>
}

export function getMultiplier(entry: TimesheetCostLine): number {
  const m = getMeta(entry).wage_rate_multiplier
  return typeof m === 'number' && Number.isFinite(m) ? m : 1.0
}

export function getIsBillable(entry: TimesheetCostLine): boolean {
  const v = getMeta(entry).is_billable
  return typeof v === 'boolean' ? v : true
}

/**
 * Wage for a time entry: hours × rate-multiplier × staff wage rate.
 * Returns 0 when hours or wage rate is non-positive.
 */
export function calculatedWage(entry: TimesheetCostLine): number {
  // Prefer wage_rate (the staff's per-hour rate at entry time); fall through to
  // unit_cost when wage_rate is 0/missing on a phantom row.
  const wageRate = entry.wage_rate && entry.wage_rate > 0 ? entry.wage_rate : (entry.unit_cost ?? 0)
  const hours = entry.quantity ?? 0
  const mult = getMultiplier(entry)
  if (hours <= 0 || wageRate <= 0) return 0
  return Math.round(hours * mult * wageRate * 100) / 100
}

/**
 * Bill for a time entry: hours × charge-out rate (only when billable).
 */
export function calculatedBill(entry: TimesheetCostLine): number {
  const billable = getIsBillable(entry)
  const rate = entry.charge_out_rate ?? entry.unit_rev ?? 0
  const hours = entry.quantity ?? 0
  if (!billable || hours <= 0 || rate <= 0) return 0
  return Math.round(hours * rate * 100) / 100
}

/**
 * Parse hours input. Accepts plain numbers, decimals, and fractional forms:
 *   "1.5", "1 1/4", "3/4". Returns the existing fallback when input is blank
 *   or unparseable, and clamps to [0, 24].
 */
export function parseHoursInput(raw: string, fallback: number): number {
  const s = (raw ?? '').trim()
  if (!s) return fallback
  let parsed: number
  const mixed = s.match(/^(\d+)\s+(\d+)\/(\d+)$/)
  if (mixed) {
    const w = parseInt(mixed[1], 10)
    const n = parseInt(mixed[2], 10)
    const d = parseInt(mixed[3], 10)
    if (d === 0) return fallback
    parsed = w + n / d
  } else {
    const frac = s.match(/^(\d+)\/(\d+)$/)
    if (frac) {
      const n = parseInt(frac[1], 10)
      const d = parseInt(frac[2], 10)
      if (d === 0) return fallback
      parsed = n / d
    } else {
      parsed = parseFloat(s)
    }
  }
  if (!Number.isFinite(parsed) || parsed < 0) return fallback
  return Math.round(Math.min(parsed, 24) * 100) / 100
}
