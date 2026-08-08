import type { JobDeltaEnvelope, JobDetail } from '@/api'
import { computeJobDeltaChecksum } from '@/lib/delta/checksum'

/** The wire fields job editing may change; anything else is server-owned. */
const JOB_EDITABLE_FIELDS = [
  'name',
  'description',
  'delivery_date',
  'order_number',
  'notes',
  'pricing_methodology',
  'speed_quality_tradeoff',
  'default_xero_pay_item_id',
  'person_id',
  'company_id',
  'job_status',
] as const

export type JobEditableField = (typeof JOB_EDITABLE_FIELDS)[number]

export type JobFieldValues = Partial<Record<JobEditableField, unknown>>

function isEditableField(value: string): value is JobEditableField {
  return (JOB_EDITABLE_FIELDS as readonly string[]).includes(value)
}

/** The editable-field snapshot of a server job, used as a delta baseline. */
export function snapshotJob(job: JobDetail): Record<JobEditableField, unknown> {
  return {
    name: job.name,
    description: job.description,
    delivery_date: job.delivery_date,
    order_number: job.order_number,
    notes: job.notes,
    pricing_methodology: job.pricing_methodology,
    speed_quality_tradeoff: job.speed_quality_tradeoff,
    default_xero_pay_item_id: job.default_xero_pay_item_id,
    person_id: job.person_id,
    company_id: job.company_id,
    job_status: job.job_status,
  }
}

/** The subset of `changes` that actually differs from the baseline. */
export function changedFieldsOnly(
  baseline: JobFieldValues,
  changes: JobFieldValues,
): JobFieldValues {
  const changed: JobFieldValues = {}
  // Object.keys erases the key union; the runtime guard restores it and
  // fail-fasts on a field the delta contract does not know.
  for (const field of Object.keys(changes)) {
    if (!isEditableField(field)) {
      throw new Error(`'${field}' is not a job-editable field`)
    }
    const value = changes[field]
    if (!(field in baseline)) {
      throw new Error(`Delta change for '${field}' has no baseline value`)
    }
    if (baseline[field] !== value) {
      changed[field] = value
    }
  }
  return changed
}

/**
 * Build the PATCH body for a job field change. The backend recomputes the
 * checksum over the `before` values and rejects a mismatch, so `baseline`
 * MUST come from the server (the last GET or PATCH response), never from
 * form state — a client-invented baseline turns every concurrent edit into
 * a checksum failure it cannot explain.
 */
export async function buildJobDeltaEnvelope(
  jobId: string,
  baseline: JobFieldValues,
  changes: JobFieldValues,
): Promise<JobDeltaEnvelope> {
  const changed = changedFieldsOnly(baseline, changes)
  const changedFields = Object.keys(changed).toSorted()
  if (changedFields.length === 0) {
    throw new Error('No fields changed in delta envelope')
  }

  const before: Record<string, unknown> = {}
  const after: Record<string, unknown> = {}
  for (const field of Object.keys(changed)) {
    if (!isEditableField(field)) {
      throw new Error(`'${field}' is not a job-editable field`)
    }
    before[field] = baseline[field]
    after[field] = changed[field]
  }

  return {
    change_id: crypto.randomUUID(),
    job_id: jobId,
    made_at: new Date().toISOString(),
    fields: changedFields,
    before,
    after,
    before_checksum: await computeJobDeltaChecksum(jobId, before, changedFields),
  }
}
