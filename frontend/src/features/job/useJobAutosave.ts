import { useCallback, useEffect, useMemo, useRef } from 'react'
import type { JobDetail } from '@/api'
import { useJobFieldSave } from './useJobFieldSave'

/** The wire fields the settings tab edits, snapshotted from the server job. */
export type JobAutosaveField =
  | 'name'
  | 'description'
  | 'delivery_date'
  | 'order_number'
  | 'notes'
  | 'pricing_methodology'
  | 'speed_quality_tradeoff'
  | 'default_xero_pay_item_id'
  | 'person_id'
  | 'company_id'

// Unset is NULL (ADR 0040): a cleared control queues null, never "".
const NULL_WHEN_EMPTY: ReadonlySet<JobAutosaveField> = new Set([
  'description',
  'order_number',
  'notes',
  'delivery_date',
  'default_xero_pay_item_id',
])

function snapshotJob(job: JobDetail): Record<JobAutosaveField, unknown> {
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
  }
}

const AUTOSAVE_DEBOUNCE_MS = 1000

/**
 * Debounced field autosave against the server baseline. Changes queue for
 * one second (or until an explicit flush on blur) and go to the backend as a
 * single delta envelope; the baseline advances only on a successful PATCH,
 * so a failed save leaves the next attempt diffing against what the server
 * still holds.
 */
export function useJobAutosave(jobId: string, serverJob: JobDetail) {
  const { save } = useJobFieldSave(jobId)
  const baselineRef = useRef<Record<string, unknown>>(snapshotJob(serverJob))
  const pendingRef = useRef<Partial<Record<JobAutosaveField, unknown>>>({})
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const savingRef = useRef<Promise<void>>(Promise.resolve())

  const flush = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const pending = pendingRef.current
    pendingRef.current = {}
    const changes: Record<string, unknown> = {}
    for (const [field, value] of Object.entries(pending)) {
      if (baselineRef.current[field] !== value) {
        changes[field] = value
      }
    }
    if (Object.keys(changes).length === 0) {
      return
    }
    // Serialise saves: a second flush while one is in flight must diff
    // against the baseline the first one produces.
    savingRef.current = savingRef.current.then(async () => {
      await save(baselineRef.current, changes)
      baselineRef.current = { ...baselineRef.current, ...changes }
    })
    // useJobFieldSave surfaces failures (concurrency toast or error toast);
    // here the chain must survive them so later saves still run.
    savingRef.current = savingRef.current.catch(() => undefined)
  }, [save])

  const queueChange = useCallback(
    (field: JobAutosaveField, value: unknown) => {
      const normalised = NULL_WHEN_EMPTY.has(field) && value === '' ? null : value
      pendingRef.current[field] = normalised
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
      }
      timerRef.current = setTimeout(flush, AUTOSAVE_DEBOUNCE_MS)
    },
    [flush],
  )

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
      }
    }
  }, [])

  return useMemo(() => ({ queueChange, flush }), [queueChange, flush])
}
