import type { JobDeltaEnvelope } from '@/api'
import { computeJobDeltaChecksum } from '@/lib/delta/checksum'

/**
 * Build the PATCH body for a job field change. The backend recomputes the
 * checksum over the `before` values and rejects a mismatch, so `baseline`
 * MUST come from the server (the last GET or PATCH response), never from
 * form state — a client-invented baseline turns every concurrent edit into
 * a checksum failure it cannot explain.
 */
export async function buildJobDeltaEnvelope(
  jobId: string,
  baseline: Record<string, unknown>,
  changes: Record<string, unknown>,
): Promise<JobDeltaEnvelope> {
  for (const field of Object.keys(changes)) {
    if (!(field in baseline)) {
      throw new Error(`Delta change for '${field}' has no baseline value`)
    }
  }

  const changedFields = Object.keys(changes)
    .filter((field) => baseline[field] !== changes[field])
    .toSorted()
  if (changedFields.length === 0) {
    throw new Error('No fields changed in delta envelope')
  }

  const before: Record<string, unknown> = {}
  const after: Record<string, unknown> = {}
  for (const field of changedFields) {
    before[field] = baseline[field]
    after[field] = changes[field]
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
