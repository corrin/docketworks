import { ref } from 'vue'
import { z } from 'zod'
import { schemas } from '../api/generated/api'
import { api } from '@/api/client'

type XeroError = z.infer<typeof schemas.XeroError>
type AppError = z.infer<typeof schemas.AppError>
type AppErrorListResponse = z.infer<typeof schemas.AppErrorListResponse>
type JobDeltaRejection = z.infer<typeof schemas.JobDeltaRejection>

interface DateRange {
  start: string | null
  end: string | null
}

type ErrorType = 'xero' | 'system' | 'job'
type ErrorResultMap = {
  xero: XeroError
  system: AppError
  job: JobDeltaRejection
}

type XeroErrorFilters = {
  search?: string
  range?: DateRange
}

type SystemErrorFilters = {
  app?: string
  severity?: number
  resolved?: boolean
  jobId?: string
  userId?: string
}

type JobErrorFilters = {
  jobId?: string
}

type ErrorFilterMap = {
  xero: XeroErrorFilters
  system: SystemErrorFilters
  job: JobErrorFilters
}

const PAGE_SIZE = 20

export function useErrorApi() {
  const error = ref<string | null>(null)

  async function fetchErrors<T extends ErrorType>(
    type: T,
    page: number,
    filters: ErrorFilterMap[T],
  ): Promise<{ results: ErrorResultMap[T][]; pageCount: number }> {
    error.value = null
    try {
      if (type === 'xero') {
        // Use Zodios API for xero errors
        // Note: search and date filtering not available in current API, would need backend update
        const response = await api.xero_errors_list(page > 1 ? { queries: { page } } : {})
        return {
          results: response.results || [],
          pageCount: response.count
            ? Math.ceil(response.count / (response.results?.length || 50))
            : 0,
        } as { results: ErrorResultMap[T][]; pageCount: number }
      }

      if (type === 'system') {
        const systemFilters = filters as SystemErrorFilters
        const offset = Math.max(page - 1, 0) * PAGE_SIZE
        const params: Record<string, unknown> = {
          limit: PAGE_SIZE,
          offset,
        }
        if (systemFilters?.app) params.app = systemFilters.app
        if (
          typeof systemFilters?.severity === 'number' &&
          Number.isFinite(systemFilters.severity)
        ) {
          params.severity = systemFilters.severity
        }
        if (typeof systemFilters?.resolved === 'boolean') {
          params.resolved = systemFilters.resolved
        }
        if (systemFilters?.jobId) params.job_id = systemFilters.jobId
        if (systemFilters?.userId) params.user_id = systemFilters.userId

        const response = await api.axios.get<AppErrorListResponse>('/rest/app-errors/', {
          params,
        })
        const payload = response.data
        return {
          results: payload.results || [],
          pageCount: payload.count ? Math.ceil(payload.count / PAGE_SIZE) : 0,
        } as { results: ErrorResultMap[T][]; pageCount: number }
      }

      if (type === 'job') {
        const jobFilters = filters as JobErrorFilters
        const offset = Math.max(page - 1, 0) * PAGE_SIZE
        const params: Record<string, unknown> = {
          limit: PAGE_SIZE,
          offset,
        }
        if (jobFilters?.jobId) {
          params.job_id = jobFilters.jobId
        }

        const response = await api.job_rest_jobs_delta_rejections_admin_list({
          queries: params,
        })
        return {
          results: response.results || [],
          pageCount: response.count ? Math.ceil(response.count / PAGE_SIZE) : 0,
        } as { results: ErrorResultMap[T][]; pageCount: number }
      }
    } catch (e: unknown) {
      if (e instanceof Error) error.value = e.message
      else error.value = 'Failed to fetch errors.'
      return { results: [] as ErrorResultMap[T][], pageCount: 0 }
    }

    return { results: [] as ErrorResultMap[T][], pageCount: 0 }
  }

  return { fetchErrors, error }
}
