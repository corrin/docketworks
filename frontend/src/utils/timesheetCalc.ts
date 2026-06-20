/**
 * Pure calculation helpers for timesheet entries.
 *
 * Backend types use snake_case (`quantity`, `unit_cost`, `total_cost`) and the
 * rate multipliers live in `meta.wage_rate_multiplier` and
 * `meta.bill_rate_multiplier`. These helpers operate
 * directly on the wire shape so SmartTimesheetTable can render derived columns
 * (Wage, Bill) without inventing camelCase aliases.
 */

import type { z } from 'zod'
import type { schemas } from '../api/generated/api'
import { requiredNumber } from './requiredNumber'

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

export function getBillMultiplier(entry: TimesheetCostLine): number {
  const meta = getMeta(entry)
  const m = meta.bill_rate_multiplier
  if (typeof m === 'number' && Number.isFinite(m)) return m
  if (meta.is_billable === false) return 0.0
  return getMultiplier(entry)
}

/**
 * Wage for a time entry: hours × rate-multiplier × staff wage rate.
 * Returns 0 when hours or wage rate is non-positive.
 */
export function calculatedWage(entry: TimesheetCostLine): number {
  // Prefer wage_rate (the staff's per-hour rate at entry time); fall through to
  // unit_cost when wage_rate is 0/missing on a phantom row.
  const wageRate =
    entry.wage_rate && entry.wage_rate > 0
      ? entry.wage_rate
      : requiredNumber(entry.unit_cost, 'timesheet entry unit_cost')
  const hours = requiredNumber(entry.quantity, 'timesheet entry quantity')
  const mult = getMultiplier(entry)
  if (hours <= 0 || wageRate <= 0) return 0
  return Math.round(hours * mult * wageRate * 100) / 100
}

/**
 * Bill for a time entry: hours × charge-out rate × bill multiplier.
 * `charge_out_rate` is the job's rate for this line's labour subtype.
 */
export function calculatedBill(entry: TimesheetCostLine): number {
  const rate =
    entry.charge_out_rate !== null && entry.charge_out_rate !== undefined
      ? requiredNumber(entry.charge_out_rate, 'timesheet entry charge_out_rate')
      : requiredNumber(entry.unit_rev, 'timesheet entry unit_rev')
  const hours = requiredNumber(entry.quantity, 'timesheet entry quantity')
  const mult = getBillMultiplier(entry)
  if (hours <= 0 || rate <= 0 || mult <= 0) return 0
  return Math.round(hours * mult * rate * 100) / 100
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
