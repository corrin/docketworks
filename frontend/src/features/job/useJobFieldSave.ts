import { useCallback, useEffect, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { apiErrorMessage, getFullJobOptions, jobJobsPartialUpdateMutation } from '@/api'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { onConcurrencyRetry } from '@/lib/concurrency/retry-bus'
import { buildJobDeltaEnvelope, changedFieldsOnly, snapshotJob, type JobFieldValues } from './delta'
import { invalidateJobViews } from './invalidateJobViews'

interface UseJobFieldSaveOptions {
  /** Called after EVERY successful save, including a Retry replay — the
   * caller's own baseline must advance on both paths or later edits diff
   * against pre-conflict values and 412 forever. */
  onSaved?: (changes: JobFieldValues) => void
}

/**
 * Save job fields through the delta contract. If-Match attaches and the new
 * ETag re-captures automatically (lib/concurrency interceptors); on a 412 the
 * interceptor toast offers Retry, and this hook replays the rejected changes
 * against the refreshed server baseline when the user clicks it.
 */
export function useJobFieldSave(jobId: string, options?: UseJobFieldSaveOptions) {
  const queryClient = useQueryClient()
  const patch = useMutation(jobJobsPartialUpdateMutation())
  // mutateAsync is referentially stable across renders; the mutation RESULT
  // object is not, and depending on it would rebuild save (and everything
  // memoised on save) every render.
  const { mutateAsync } = patch
  const rejectedChanges = useRef<JobFieldValues | null>(null)
  const onSavedRef = useRef(options?.onSaved)
  onSavedRef.current = options?.onSaved

  const save = useCallback(
    async (baseline: JobFieldValues, changes: JobFieldValues): Promise<void> => {
      // A commit of an unchanged value is an ordinary user action (blur on an
      // untouched inline edit), not an error.
      if (Object.keys(changedFieldsOnly(baseline, changes)).length === 0) {
        return
      }
      const envelope = await buildJobDeltaEnvelope(jobId, baseline, changes)
      try {
        await mutateAsync({ path: { job_id: jobId }, body: envelope })
      } catch (error) {
        // Merge, not replace: a second failed flush must not make Retry
        // forget the first one's fields.
        rejectedChanges.current = { ...rejectedChanges.current, ...changes }
        throw error
      }
      // Clear only what this save carried: an unrelated success must not
      // make Retry forget an earlier rejected batch.
      if (rejectedChanges.current !== null) {
        const saved = new Set(Object.keys(changes))
        const remaining = Object.fromEntries(
          Object.entries(rejectedChanges.current).filter(([field]) => !saved.has(field)),
        )
        rejectedChanges.current = Object.keys(remaining).length > 0 ? remaining : null
      }
      onSavedRef.current?.(changes)
      // Awaited: the next edit diffs against the baseline this refetch brings
      // back, so returning before it lands would let a second keystroke build
      // its delta from the pre-save values.
      await invalidateJobViews(queryClient, jobId)
    },
    [jobId, mutateAsync, queryClient],
  )

  useEffect(() => {
    return onConcurrencyRetry('job', jobId, () => {
      const changes = rejectedChanges.current
      if (changes === null) {
        return
      }
      // The 412 interceptor invalidated the job, so the cache now holds the
      // other writer's version — that is the only honest baseline to replay
      // against. A repeat failure re-enters the interceptor's own toast/retry
      // path; anything else must toast, not surface as an uncaught rejection
      // (the E2E console guard fails the spec on those).
      void (async () => {
        const fresh = await queryClient.ensureQueryData(
          getFullJobOptions({ path: { job_id: jobId } }),
        )
        await save(snapshotJob(fresh.data.job), changes)
      })().catch((error: unknown) => {
        if (!isConcurrencyError(error)) {
          toast.error(apiErrorMessage(error, 'Retrying the save failed.'))
        }
      })
    })
  }, [jobId, queryClient, save])

  return { save, isSaving: patch.isPending }
}
