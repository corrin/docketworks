import { useCallback, useEffect, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { apiErrorMessage, getFullJobOptions, jobJobsPartialUpdateMutation } from '@/api'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { onConcurrencyRetry } from '@/lib/concurrency/retry-bus'
import { buildJobDeltaEnvelope } from './delta'

/**
 * Save job fields through the delta contract. If-Match attaches and the new
 * ETag re-captures automatically (lib/concurrency interceptors); on a 412 the
 * interceptor toast offers Retry, and this hook replays the rejected changes
 * against the refreshed server baseline when the user clicks it.
 */
export function useJobFieldSave(jobId: string) {
  const queryClient = useQueryClient()
  const patch = useMutation(jobJobsPartialUpdateMutation())
  const rejectedChanges = useRef<Record<string, unknown> | null>(null)

  const save = useCallback(
    async (baseline: Record<string, unknown>, changes: Record<string, unknown>): Promise<void> => {
      const envelope = await buildJobDeltaEnvelope(jobId, baseline, changes)
      try {
        await patch.mutateAsync({ path: { job_id: jobId }, body: envelope })
      } catch (error) {
        rejectedChanges.current = changes
        throw error
      }
      rejectedChanges.current = null
      await queryClient.invalidateQueries({
        queryKey: getFullJobOptions({ path: { job_id: jobId } }).queryKey,
      })
    },
    [jobId, patch, queryClient],
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
        const baseline: Record<string, unknown> = { ...fresh.data.job }
        await save(baseline, changes)
      })().catch((error: unknown) => {
        if (!isConcurrencyError(error)) {
          toast.error(apiErrorMessage(error, 'Retrying the save failed.'))
        }
      })
    })
  }, [jobId, queryClient, save])

  return { save, isSaving: patch.isPending }
}
