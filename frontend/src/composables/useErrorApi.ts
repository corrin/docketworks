import { ref } from 'vue'
import { z } from 'zod'
import { schemas } from '../api/generated/api'
import { api } from '@/api/client'

type XeroError = z.infer<typeof schemas.XeroError>
type AppError = z.infer<typeof schemas.AppError>
type AppErrorListResponse = z.infer<typeof schemas.AppErrorListResponse>
type JobDeltaRejection = z.infer<typeof schemas.JobDeltaRejection>
type GroupedAppError = z.infer<typeof schemas.GroupedAppError>
type GroupedAppErrorListResponse = z.infer<typeof schemas.GroupedAppErrorListResponse>
type GroupedJobDeltaRejection = z.infer<typeof schemas.GroupedJobDeltaRejection>
type GroupedJobDeltaRejectionListResponse = z.infer<
  typeof schemas.GroupedJobDeltaRejectionListResponse
>

type GroupedResultMap = {
  xero: GroupedAppError
  system: GroupedAppError
  job: GroupedJobDeltaRejection
}

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

  async function fetchGroupedErrors<T extends ErrorType>(
    type: T,
    page: number,
    filters: ErrorFilterMap[T],
  ): Promise<{ results: GroupedResultMap[T][]; pageCount: number }> {
    error.value = null
    const offset = Math.max(page - 1, 0) * PAGE_SIZE
    try {
      if (type === 'xero') {
        const xeroFilters = filters as XeroErrorFilters
        const params: Record<string, unknown> = { limit: PAGE_SIZE, offset }
        if (xeroFilters?.search) params.search = xeroFilters.search
        const response = await api.axios.get<GroupedAppErrorListResponse>(
          '/api/xero-errors/grouped/',
          { params },
        )
        return mapGroupedResponse<T>(response.data)
      }

      if (type === 'system') {
        const systemFilters = filters as SystemErrorFilters
        const params: Record<string, unknown> = { limit: PAGE_SIZE, offset }
        if (systemFilters?.app) params.app = systemFilters.app
        if (typeof systemFilters?.severity === 'number') {
          params.severity = systemFilters.severity
        }
        if (typeof systemFilters?.resolved === 'boolean') {
          params.resolved = systemFilters.resolved
        }
        if (systemFilters?.jobId) params.job_id = systemFilters.jobId
        if (systemFilters?.userId) params.user_id = systemFilters.userId
        const response = await api.axios.get<GroupedAppErrorListResponse>(
          '/api/app-errors/grouped/',
          { params },
        )
        return mapGroupedResponse<T>(response.data)
      }

      const jobFilters = filters as JobErrorFilters
      const params: Record<string, unknown> = { limit: PAGE_SIZE, offset }
      if (jobFilters?.jobId) params.job_id = jobFilters.jobId
      const response = await api.axios.get<GroupedJobDeltaRejectionListResponse>(
        '/api/job/jobs/delta-rejections/grouped/',
        { params },
      )
      return mapGroupedResponse<T>(response.data)
    } catch (e: unknown) {
      if (e instanceof Error) error.value = e.message
      else error.value = 'Failed to fetch grouped errors.'
      return { results: [] as GroupedResultMap[T][], pageCount: 0 }
    }
  }

  function mapGroupedResponse<T extends ErrorType>(
    payload: GroupedAppErrorListResponse | GroupedJobDeltaRejectionListResponse,
  ): { results: GroupedResultMap[T][]; pageCount: number } {
    return {
      results: (payload.results ?? []) as GroupedResultMap[T][],
      pageCount: payload.count ? Math.ceil(payload.count / PAGE_SIZE) : 0,
    }
  }

  async function resolveGroup(
    type: ErrorType,
    keyField: 'message' | 'reason',
    keyValue: string,
    action: 'mark_resolved' | 'mark_unresolved',
  ): Promise<number> {
    const endpoint =
      type === 'xero'
        ? `/api/xero-errors/grouped/${action}/`
        : type === 'system'
          ? `/api/app-errors/grouped/${action}/`
          : `/api/job/jobs/delta-rejections/grouped/${action}/`
    const body = { [keyField]: keyValue }
    const response = await api.axios.post<{ updated: number }>(endpoint, body)
    return response.data.updated
  }

  return { fetchErrors, fetchGroupedErrors, resolveGroup, error }
}
