/**
 * Meta readers for server timesheet lines (v1 timesheetCalc getters).
 * One implementation: the grid's cells and the entry page's tiles must agree
 * on what counts as billable.
 */

import type { TimesheetCostLineOut } from '@/api'

export function lineMeta(line: TimesheetCostLineOut): Record<string, unknown> {
  return line.meta
}

export function lineWageMultiplier(line: TimesheetCostLineOut): number {
  const value = lineMeta(line).wage_rate_multiplier
  return typeof value === 'number' && Number.isFinite(value) ? value : 1.0
}

export function lineIsBillable(line: TimesheetCostLineOut): boolean {
  const value = lineMeta(line).is_billable
  return typeof value === 'boolean' ? value : true
}

export function lineBillMultiplier(line: TimesheetCostLineOut): number {
  const value = lineMeta(line).bill_rate_multiplier
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (!lineIsBillable(line)) return 0.0
  return lineWageMultiplier(line)
}
