/**
 * Pure helpers for a job's per-labour-subtype charge-out rates (v1-exact).
 *
 * Jobs expose `labour_rates` (one entry per active labour subtype). Time cost
 * lines carry a `labour_subtype`; their revenue rate is the job's rate for
 * that subtype. When a line has no subtype yet (a new timesheet row before
 * the backend applies the worker's default), the workshop rate is the
 * display fallback.
 */

import type { JobLabourRateOut } from '@/api'

/**
 * The job's workshop rate entry: the first `is_workshop` entry (the backend
 * orders labour_rates by subtype display_order), else the first entry.
 */
export function workshopRateEntry(
  rates: readonly JobLabourRateOut[],
): JobLabourRateOut | undefined {
  return rates.find((rate) => rate.is_workshop) ?? rates[0]
}

/**
 * Charge-out rate for a labour subtype on this job.
 * Falls back to the workshop rate only when the subtype is unset. Missing job
 * rates or unknown subtype IDs are contract/data errors, not zero-rate cases.
 */
export function rateForSubtype(
  rates: readonly JobLabourRateOut[],
  labourSubtypeId: string | null | undefined,
): number {
  const hasSubtype = labourSubtypeId !== null && labourSubtypeId !== undefined
  const entry = hasSubtype
    ? rates.find((rate) => rate.labour_subtype === labourSubtypeId)
    : workshopRateEntry(rates)
  if (!entry) {
    throw new Error(
      hasSubtype
        ? `No job labour rate for subtype ${labourSubtypeId}`
        : 'No workshop job labour rate available',
    )
  }
  const parsed = Number(entry.charge_out_rate)
  if (!Number.isFinite(parsed)) {
    throw new Error(`charge_out_rate for ${entry.labour_subtype_name} is not a number`)
  }
  return parsed
}

/** Display name of a subtype on this job, or null when unset/unknown. */
export function subtypeName(
  rates: readonly JobLabourRateOut[],
  subtypeId: string | null | undefined,
): string | null {
  if (!subtypeId) return null
  return rates.find((rate) => rate.labour_subtype === subtypeId)?.labour_subtype_name ?? null
}
