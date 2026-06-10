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
