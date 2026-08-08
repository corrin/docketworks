import { useCallback, useEffect, useMemo, useRef } from 'react'
import { toast } from 'sonner'

import { apiErrorMessage, type JobDetail } from '@/api'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { snapshotJob, type JobEditableField, type JobFieldValues } from './delta'
import { useJobFieldSave } from './useJobFieldSave'

// Unset is NULL (ADR 0040): a cleared control queues null, never "".
const NULL_WHEN_EMPTY: ReadonlySet<JobEditableField> = new Set([
  'description',
  'order_number',
  'notes',
  'delivery_date',
  'default_xero_pay_item_id',
])

const AUTOSAVE_DEBOUNCE_MS = 1000

/**
 * Debounced field autosave against the server baseline. Changes queue for
 * one second (or until an explicit flush on blur) and go to the backend as a
 * single delta envelope; the baseline advances only on a successful PATCH,
 * so a failed save leaves the next attempt diffing against what the server
 * still holds.
 */
export function useJobAutosave(jobId: string, serverJob: JobDetail) {
  const baselineRef = useRef<JobFieldValues>(snapshotJob(serverJob))
  const { save } = useJobFieldSave(jobId, {
    onSaved: (changes) => {
      baselineRef.current = { ...baselineRef.current, ...changes }
    },
  })
  const pendingRef = useRef<JobFieldValues>({})
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const savingRef = useRef<Promise<void>>(Promise.resolve())

  // The header edits fields this tab also holds (name, status, pricing);
  // its PATCH refetches the job, and without this resync every later edit
  // here would diff against a pre-header-edit baseline and 412 against the
  // page's own change. Pending edits keep their queued values — they diff
  // at flush time.
  useEffect(() => {
    baselineRef.current = snapshotJob(serverJob)
  }, [serverJob])

  const flush = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const pending = pendingRef.current
    pendingRef.current = {}
    if (Object.keys(pending).length === 0) {
      return
    }
    // Serialise saves, and diff INSIDE the chain: a revert typed while the
    // previous save is in flight must compare against the baseline that save
    // produces, or the revert is silently dropped.
    savingRef.current = savingRef.current
      .then(() => save(baselineRef.current, pending))
      .catch((error: unknown) => {
        // The chain must survive failures so later saves still run, and a
        // swallowed error here would let edits vanish with zero feedback —
        // concurrency failures already toast via the interceptor.
        if (!isConcurrencyError(error)) {
          toast.error(apiErrorMessage(error, 'Failed to save the job.'))
        }
      })
  }, [save])

  const queueChange = useCallback(
    (field: JobEditableField, value: unknown) => {
      const normalised = NULL_WHEN_EMPTY.has(field) && value === '' ? null : value
      pendingRef.current[field] = normalised
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
      }
      timerRef.current = setTimeout(flush, AUTOSAVE_DEBOUNCE_MS)
    },
    [flush],
  )

  const flushRef = useRef(flush)
  flushRef.current = flush

  useEffect(() => {
    return () => {
      // A pending debounce on unmount is a typed edit the user expects to
      // keep — flush it (fire-and-forget; unmount cannot await). Mount-only
      // via a ref: keying this effect on flush would run the cleanup — and
      // therefore a flush — on every render that changes flush's identity,
      // which is a mid-typing save.
      flushRef.current()
    }
  }, [])

  return useMemo(() => ({ queueChange, flush }), [queueChange, flush])
}
