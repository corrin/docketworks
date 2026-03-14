import { AxiosError } from 'axios'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type JobDeltaEnvelope = z.infer<typeof schemas.PatchedJobDeltaEnvelopeRequest>
type JobDetailResponse = z.infer<typeof schemas.JobDetailResponse>

function extractErrorMessage(err: unknown): string {
  if (typeof err === 'string') return err
  if (err instanceof Error) return err.message
  if (typeof err === 'object' && err) {
    if ('message' in err && typeof err.message === 'string') {
      return err.message
    }
    if ('error' in err && typeof (err as { error?: string }).error === 'string') {
      return (err as { error?: string }).error as string
    }
  }
  return 'Unknown delta submission error'
}

export async function submitJobDelta(
  jobId: string,
  envelope: JobDeltaEnvelope,
): Promise<{ success: true; data: JobDetailResponse } | { success: false; error: string }> {
  try {
    const response = await api.job_rest_jobs_partial_update(envelope, {
      params: { job_id: jobId },
    })
    return { success: true, data: response }
  } catch (err) {
    if (err instanceof AxiosError) {
      const serverMsg =
        (err.response?.data as { error?: string })?.error ||
        (err.response?.data as { detail?: string })?.detail
      return { success: false, error: serverMsg || err.message }
    }
    return { success: false, error: extractErrorMessage(err) }
  }
}
