import type { TimesheetJobOut } from '@/api'

/**
 * The entry grid's draft row. Multipliers live here exactly as they will go
 * into the create payload's meta — the urgent spec asserts them verbatim on
 * the wire.
 */
export interface TimesheetDraft {
  job: TimesheetJobOut | null
  hours: number
  description: string
  labour_subtype: string | null
  is_billable: boolean
  wage_rate_multiplier: number
  bill_rate_multiplier: number
  /** The user chose a bill rate on this row; job-pick defaults must not touch it. */
  billExplicit: boolean
}

export function emptyTimesheetDraft(): TimesheetDraft {
  return {
    job: null,
    hours: 0,
    description: '',
    labour_subtype: null,
    is_billable: true,
    wage_rate_multiplier: 1.0,
    bill_rate_multiplier: 1.0,
    billExplicit: false,
  }
}

export function draftIsEmpty(draft: TimesheetDraft): boolean {
  return draft.job === null && draft.hours === 0 && draft.description.trim() === ''
}

/** Ready to POST: a job and positive hours (v1's isEntryReady). */
export function draftIsReady(draft: TimesheetDraft): boolean {
  return draft.job !== null && draft.hours > 0
}

/**
 * The billing-defaults precedence on job pick, ported exactly (v1 setJob):
 *
 * 1. A non-billable job (shop work or status 'special') forces
 *    is_billable false / bill 0.0 — and wins over urgent AND over an
 *    explicit user override.
 * 2. Otherwise, if the user has not explicitly chosen a bill rate on this
 *    row, the bill multiplier defaults to 1.5 for urgent jobs and 1.0 for
 *    the rest — which also RESETS a stale 1.5 left by a previously picked
 *    urgent job on the same unsaved row.
 * 3. An explicit override survives a repick untouched.
 *
 * The wage multiplier never changes here: urgency raises the customer
 * charge, not the wage.
 */
export function applyJobPick(draft: TimesheetDraft, job: TimesheetJobOut): TimesheetDraft {
  // A subtype from a previously picked job clears unless the new job also
  // carries it — a stale id would price (and render) against a rate row the
  // job does not have.
  const subtypeKept =
    draft.labour_subtype !== null &&
    job.labour_rates.some((rate) => rate.labour_subtype === draft.labour_subtype)
  const base = { ...draft, job, labour_subtype: subtypeKept ? draft.labour_subtype : null }
  if (job.shop_job || job.status === 'special') {
    return { ...base, is_billable: false, bill_rate_multiplier: 0.0 }
  }
  if (!draft.billExplicit) {
    return {
      ...base,
      is_billable: true,
      bill_rate_multiplier: job.is_urgent ? 1.5 : 1.0,
    }
  }
  return base
}
