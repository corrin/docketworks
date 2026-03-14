import { v4 as uuidv4 } from 'uuid'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import { computeJobDeltaChecksum } from '@/utils/deltaChecksum'

type JobDeltaEnvelope = z.infer<typeof schemas.JobDeltaEnvelopeRequest>

/**
 * Compute SHA-256 hash of HTML/content for telemetry/debugging purposes.
 * Falls back to a simple hash when Web Crypto is unavailable (e.g. during SSR/tests).
 */
async function computeHtmlHash(html: unknown): Promise<string> {
  const text = typeof html === 'string' ? html : JSON.stringify(html ?? null)

  if (typeof crypto !== 'undefined' && typeof crypto.subtle !== 'undefined') {
    try {
      const encoder = new TextEncoder()
      const data = encoder.encode(text)
      const hashBuffer = await crypto.subtle.digest('SHA-256', data)
      const hashArray = Array.from(new Uint8Array(hashBuffer))
      return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('')
    } catch {
      // Fall through to non-crypto fallback
    }
  }

  let hash = 0
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash << 5) - hash + text.charCodeAt(i)
    hash |= 0
  }
  return `fallback-${(hash >>> 0).toString(16)}`
}

type EnvelopeInput = Partial<JobDeltaEnvelope> & {
  job_id: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  fields: string[]
}

const changeQueueCache = new Map<string, { patchKey: string; changeId: string }>()

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((v) => stableValue(v))
  }
  if (value && typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        acc[key] = stableValue((value as Record<string, unknown>)[key])
        return acc
      }, {})
  }
  return value
}

function stableStringify(obj: Record<string, unknown>): string {
  const sorted = stableValue(obj)
  return JSON.stringify(sorted)
}

export function useJobDeltaQueue(jobId: string) {
  function getOrCreateChangeId(patch: Record<string, unknown>): string {
    const patchKey = stableStringify(patch)
    const existing = changeQueueCache.get(jobId)
    if (existing && existing.patchKey === patchKey) {
      return existing.changeId
    }
    const changeId = uuidv4()
    changeQueueCache.set(jobId, { patchKey, changeId })
    return changeId
  }

  function clearChangeId() {
    changeQueueCache.delete(jobId)
  }

  return {
    getOrCreateChangeId,
    clearChangeId,
  }
}

/**
 * Build a Job Delta envelope for sending updates to the server.
 * The telemetry hashes help diagnose checksum mismatches but are ignored by the backend.
 */
export async function buildJobDeltaEnvelope(input: EnvelopeInput): Promise<JobDeltaEnvelope> {
  const allFields = [...new Set(input.fields)].sort()

  // Filter to only fields where before !== after
  const changedFields = allFields.filter((field) => {
    const beforeValue = input.before[field]
    const afterValue = input.after[field]
    // Simple equality check (should work for primitives and objects that are the same reference)
    return beforeValue !== afterValue
  })

  if (changedFields.length === 0) {
    throw new Error('No fields changed in delta envelope')
  }

  // Capture before/after for telemetry (not validation)
  const before = changedFields.reduce<Record<string, unknown>>((acc, key) => {
    acc[key] = input.before[key]
    return acc
  }, {})
  const after = changedFields.reduce<Record<string, unknown>>((acc, key) => {
    acc[key] = input.after[key]
    return acc
  }, {})

  const change_id = input.change_id ?? uuidv4()
  const made_at = input.made_at ?? new Date().toISOString()
  const actor_id = input.actor_id ?? null
  const etag = input.etag ?? null

  const before_checksum = await computeJobDeltaChecksum(input.job_id, before, changedFields)
  const telemetry_before_hash = await computeHtmlHash(before)
  const telemetry_after_hash = await computeHtmlHash(after)

  const envelope: Record<string, unknown> = {
    change_id,
    actor_id,
    made_at,
    job_id: input.job_id,
    fields: changedFields,
    before,
    after,
    before_checksum,
    etag,
    telemetry_before_hash,
    telemetry_after_hash,
  }

  return schemas.JobDeltaEnvelopeRequest.parse(envelope) as JobDeltaEnvelope
}
