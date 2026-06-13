/**
 * Pure helpers for a job's per-labour-subtype charge-out rates.
 *
 * Jobs expose `labour_rates` (one entry per active labour subtype) instead of
 * a single job-level charge_out_rate. Time cost lines carry a
 * `labour_subtype`; their revenue rate is the job's rate for that subtype.
 * When a line has no subtype yet (e.g. a new timesheet row before the backend
 * applies the worker's default), the workshop rate is the display fallback.
 */

import type { z } from 'zod'
import type { schemas } from '../api/generated/api'

export type JobLabourRate = z.infer<typeof schemas.JobLabourRate>

/**
 * The job's workshop rate entry: the first `is_workshop` entry (the backend
 * orders labour_rates by subtype display_order), else the first entry.
 */
export function workshopRateEntry(rates: JobLabourRate[]): JobLabourRate | undefined {
  return rates.find((r) => r.is_workshop) ?? rates[0]
}

/**
 * Charge-out rate for a labour subtype on this job.
 * Falls back to the workshop rate when the subtype is unset/unknown, and to 0
 * when the job has no labour rates loaded at all.
 */
export function rateForSubtype(
  rates: JobLabourRate[],
  labourSubtypeId: string | null | undefined,
): number {
  const bySubtype = labourSubtypeId
    ? rates.find((r) => r.labour_subtype === labourSubtypeId)
    : undefined
  const entry = bySubtype ?? workshopRateEntry(rates)
  return entry?.charge_out_rate ?? 0
}

/**
 * Labour picker items use a prefixed id (`labour:<subtype uuid>`) so they can
 * share the string `modelValue` plumbing with stock items (plain UUIDs)
 * without colliding, and the table can parse the subtype back out.
 */
export const LABOUR_ITEM_PREFIX = 'labour:'

/** Picker item id for a labour subtype. */
export function labourItemId(subtypeId: string): string {
  return `${LABOUR_ITEM_PREFIX}${subtypeId}`
}

/** Subtype id from a picker item id, or null when the value is not a labour id. */
export function parseLabourItemId(val: string | null): string | null {
  if (!val || !val.startsWith(LABOUR_ITEM_PREFIX)) return null
  return val.slice(LABOUR_ITEM_PREFIX.length)
}

/** Display name of a subtype on this job, or null when unset/unknown. */
export function subtypeName(
  rates: JobLabourRate[],
  subtypeId: string | null | undefined,
): string | null {
  if (!subtypeId) return null
  return rates.find((r) => r.labour_subtype === subtypeId)?.labour_subtype_name ?? null
}

/**
 * Description to apply when a labour subtype is picked for a line.
 *
 * Replaces the current description with the new subtype's name when it is
 * still an auto-prefill: empty/whitespace, the legacy 'Labour' prefill, or
 * exactly some subtype name from `rates`. User-authored text is preserved.
 */
export function nextLabourDesc(
  currentDesc: string,
  rate: JobLabourRate,
  rates: JobLabourRate[],
): string {
  const trimmed = currentDesc.trim()
  const isAutoPrefill =
    trimmed === '' || trimmed === 'Labour' || rates.some((r) => r.labour_subtype_name === trimmed)
  return isAutoPrefill ? rate.labour_subtype_name : currentDesc
}
