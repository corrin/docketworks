import { schemas } from '../api/generated/api'
import { api } from '../api/client'
import axios from '../plugins/axios'
import { z } from 'zod'
import { type AdvancedFilters } from '../constants/advanced-filters'
import { AxiosError } from 'axios'
import { debugLog } from '../utils/debug'
import { buildJobDeltaEnvelope, useJobDeltaQueue } from '../composables/useJobDelta'
import { useAuthStore } from '../stores/auth'
import { useJobETags } from '../composables/useJobETags'

/**
 * Updates partial Job fields using PATCH endpoint with JobDelta envelope
 */
async function updateJobHeaderPartial(
  jobId: string,
  payload: Record<string, unknown>,
  beforeSnapshot?: Record<string, unknown>,
): Promise<{ success: true; data: JobDetailResponse } | { success: false; error: string }> {
  try {
    const keys = Object.keys(payload || {})
    debugLog('[jobService.updateJobHeaderPartial] request', { jobId, keys })

    // normalizer to ensure checksum parity with backend (nullable fields use null, not '')
    const nullableKeys = new Set([
      'description',
      'order_number',
      'notes',
      'delivery_date',
      'quote_acceptance_date',
      'price_cap',
      'default_xero_pay_item_id',
      // include 'contact_name' if ever present
      'contact_name',
    ])
    const normalizeBefore = (k: string, v: unknown) => {
      if (v === undefined) return nullableKeys.has(k) ? null : v
      if (v === '') return nullableKeys.has(k) ? null : ''
      return v
    }

    // Use provided before snapshot, or get from server as fallback (should not happen in normal flow)
    const beforeValues: Record<string, unknown> = {}

    if (beforeSnapshot) {
      // Extract before values from provided snapshot with normalization
      for (const field of keys) {
        beforeValues[field] = normalizeBefore(field, beforeSnapshot[field])
      }
      debugLog('[jobService.updateJobHeaderPartial] using client snapshot', { jobId, keys })
    } else {
      // Fallback: get from server (should not happen in normal delta flow)
      debugLog('[jobService.updateJobHeaderPartial] FALLBACK: fetching from server', {
        jobId,
        keys,
      })
      const currentJob = await api.getJobSummary({ params: { job_id: jobId } })

      for (const field of keys) {
        switch (field) {
          case 'name':
            beforeValues[field] = currentJob.data.job.name
            break
          case 'client_id':
            beforeValues[field] = currentJob.data.job.client_id
            break
          case 'client_name':
            beforeValues[field] = currentJob.data.job.client_name
            break
          case 'job_status':
            beforeValues[field] = currentJob.data.job.job_status
            break
          case 'pricing_methodology':
            beforeValues[field] = currentJob.data.job.pricing_methodology
            break
          case 'quoted':
            beforeValues[field] = currentJob.data.job.quoted
            break
          case 'fully_invoiced':
            beforeValues[field] = currentJob.data.job.fully_invoiced
            break
          case 'paid':
            beforeValues[field] = currentJob.data.job.paid
            break
          case 'quote_acceptance_date':
            beforeValues[field] = currentJob.data.job.quote_acceptance_date
            break
          case 'description':
            beforeValues[field] = currentJob.data.job.description
            break
          case 'delivery_date':
            beforeValues[field] = currentJob.data.job.delivery_date
            break
          case 'order_number':
            beforeValues[field] = currentJob.data.job.order_number
            break
          case 'notes':
            beforeValues[field] = currentJob.data.job.notes
            break
          case 'price_cap':
            beforeValues[field] = currentJob.data.job.price_cap
            break
          case 'default_xero_pay_item_id':
            beforeValues[field] = currentJob.data.job.default_xero_pay_item_id
            break
          default:
            beforeValues[field] = (currentJob.data.job as Record<string, unknown>)[field]
        }
        beforeValues[field] = normalizeBefore(field, beforeValues[field])
      }
    }

    // Get auth and etag stores
    const authStore = useAuthStore()
    const etagStore = useJobETags()
    const deltaQueue = useJobDeltaQueue(jobId)

    const actorId = authStore.user?.id ?? null
    if (!actorId) {
      return { success: false, error: 'Missing actor id' }
    }

    const changeId = deltaQueue.getOrCreateChangeId(payload)
    const etag = etagStore.getETag(jobId)

    // Build JobDelta envelope
    const envelope = await buildJobDeltaEnvelope({
      job_id: jobId,
      change_id: changeId,
      actor_id: actorId,
      made_at: new Date().toISOString(),
      etag,
      before: beforeValues,
      after: payload,
      fields: keys,
    })

    const res = await api.job_rest_jobs_partial_update(envelope, {
      params: { job_id: jobId },
    })

    deltaQueue.clearChangeId()

    debugLog('[jobService.updateJobHeaderPartial] response', {
      jobId,
      keys,
      ok: true,
    })
    return { success: true, data: res }
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Unknown error updating job header'
    debugLog('[jobService.updateJobHeaderPartial] error', { jobId, error: msg })
    return { success: false, error: msg }
  }
}

type AdvancedSearchResponse = z.infer<typeof schemas.AdvancedSearchResponse>
type KanbanJob = z.infer<typeof schemas.KanbanJob>
export type JobCreateData = z.infer<typeof schemas.JobCreateRequest>
type JobDetailResponse = z.infer<typeof schemas.JobDetailResponse>
type JobCreateResponse = z.infer<typeof schemas.JobCreateResponse>
type JobDeleteResponse = z.infer<typeof schemas.JobDeleteResponse>
type JobSummaryResponse = z.infer<typeof schemas.JobSummaryResponse>
type QuoteImportStatusResponse = z.infer<typeof schemas.QuoteImportStatusResponse>
type JobStatusUpdateResponse = z.infer<typeof schemas.KanbanSuccessResponse>
type ArchiveJobsRequest = z.infer<typeof schemas.ArchiveJobsRequest>
type JobFile = z.infer<typeof schemas.JobFile>
type JobFileRequest = z.infer<typeof schemas.JobFileRequest>
type FetchAllJobsResponse = z.infer<typeof schemas.FetchAllJobsResponse>
type FetchJobsResponse = z.infer<typeof schemas.FetchJobsResponse>
type FetchJobsByColumnResponse = z.infer<typeof schemas.FetchJobsByColumnResponse>
type FetchStatusValuesResponse = z.infer<typeof schemas.FetchStatusValuesResponse>
type CompanyDefaults = z.infer<typeof schemas.CompanyDefaults>
type PaginatedCompleteJobList = z.infer<typeof schemas.PaginatedCompleteJobList>
type JobReorderPayload = z.infer<typeof schemas.JobReorderRequest>

/**
 * Clean job service using ONLY Zodios API
 */
export const jobService = {
  // Job retrieval
  getAllJobs(): Promise<FetchAllJobsResponse> {
    return api.job_api_jobs_fetch_all_retrieve()
  },

  // Partial update for header autosave
  updateJobHeaderPartial,

  getJobsByStatus(status: string): Promise<FetchJobsResponse> {
    return api.job_api_jobs_fetch_retrieve({ params: { status } })
  },

  getJobsByColumn(columnId: string): Promise<FetchJobsByColumnResponse> {
    return api.job_api_jobs_fetch_by_column_retrieve({
      params: { column_id: columnId },
    })
  },

  getStatusChoices(): Promise<FetchStatusValuesResponse> {
    return Promise.resolve({
      success: true,
      statuses: {
        draft: 'Draft',
        awaiting_approval: 'Awaiting Approval',
        approved: 'Approved',
        in_progress: 'In Progress',
        unusual: 'Unusual',
        recently_completed: 'Recently Completed',
      },
      tooltips: {
        draft: 'Initial job creation - quote being prepared',
        awaiting_approval: 'Quote submitted and waiting for customer approval',
        approved: 'Quote approved and ready to start work',
        in_progress: 'Work has started on this job',
        unusual: 'Jobs requiring special attention or unusual circumstances',
        recently_completed: 'Work has just finished on this job',
      },
    })
    // return api.job_api_jobs_status_values_retrieve()
  },

  // Job CRUD
  createJob(jobData: JobCreateData): Promise<JobCreateResponse> {
    return api.job_rest_jobs_create(jobData)
  },

  getJob(jobId: string): Promise<JobDetailResponse> {
    return api.getFullJob({ params: { job_id: jobId } })
  },

  getJobSummary(jobId: string): Promise<JobSummaryResponse> {
    return api.getJobSummary({ params: { job_id: jobId } })
  },

  deleteJob(jobId: string): Promise<{ success: boolean; error?: string; message?: string }> {
    return api
      .job_rest_jobs_destroy(undefined, { params: { job_id: jobId } })
      .then((response: JobDeleteResponse) => ({
        success: response.success,
        message: response.message,
      }))
      .catch((error: unknown) => {
        console.error('[deleteJob] erro ao deletar job', error)

        let msg = 'Failed to delete job'

        if ((error as AxiosError).isAxiosError) {
          const axiosErr = error as AxiosError<{ error: string }>
          msg = axiosErr.response?.data?.error ?? msg
        }

        return {
          success: false,
          error: msg,
        }
      })
  },

  // Archive
  getCompletedJobs(): Promise<PaginatedCompleteJobList> {
    return api.job_api_job_completed_list()
  },

  archiveJobs(jobIds: string[]): Promise<ArchiveJobsRequest> {
    return api.job_api_job_completed_archive_create({ ids: jobIds })
  },

  // Files
  listJobFiles(jobId: string): Promise<JobFile[]> {
    return api.listJobFiles({
      params: { job_id: jobId },
    })
  },

  // PDF
  async getWorkshopPdf(jobId: string): Promise<Blob> {
    try {
      const response = await axios.get(`/job/rest/jobs/${jobId}/workshop-pdf/`, {
        responseType: 'blob',
      })
      return response.data
    } catch (error) {
      console.error('Error fetching workshop PDF:', error)
      throw error
    }
  },

  async getDeliveryDocket(jobId: string): Promise<Blob> {
    try {
      const response = await axios.get(`/job/rest/jobs/${jobId}/delivery-docket/`, {
        responseType: 'blob',
      })
      return response.data
    } catch (error) {
      console.error('Error fetching delivery docket:', error)
      throw error
    }
  },

  // Settings
  getCompanyDefaults(): Promise<CompanyDefaults> {
    return api.api_company_defaults_retrieve()
  },

  // Quote
  getQuoteStatus(jobId: string): Promise<QuoteImportStatusResponse> {
    return api.job_rest_jobs_quote_status_retrieve({ params: { job_id: jobId } })
  },

  // Local search
  searchJobsLocal(jobs: KanbanJob[], query: string): KanbanJob[] {
    if (!query) return jobs

    const searchTerm = query.toLowerCase()
    return jobs.filter(
      (job) =>
        job.name?.toLowerCase().includes(searchTerm) ||
        job.client_name?.toLowerCase().includes(searchTerm) ||
        String(job.job_number).toLowerCase().includes(searchTerm) ||
        job.description?.toLowerCase().includes(searchTerm),
    )
  },

  performAdvancedSearch(filters: AdvancedFilters): Promise<AdvancedSearchResponse> {
    // Process filters to ensure status array is properly formatted
    const processedFilters = {
      ...filters,
      // Convert status array to comma-separated string if it's an array
      status:
        Array.isArray(filters.status) && filters.status.length > 0 ? filters.status.join(',') : '',
    }

    console.log('Advanced search filters:', processedFilters)
    return api.job_api_jobs_advanced_search_retrieve({ queries: processedFilters })
  },

  // Update job status
  updateJobStatus(jobId: string, newStatus: string): Promise<JobStatusUpdateResponse> {
    debugLog('[jobService.updateJobStatus] ->', { jobId, newStatus })
    return api
      .job_api_jobs_update_status_create({ status: newStatus }, { params: { job_id: jobId } })
      .then((r) => {
        debugLog('[jobService.updateJobStatus] ok', { jobId, newStatus })
        return r
      })
      .catch((e) => {
        const msg = e instanceof Error ? e.message : String(e)
        debugLog('[jobService.updateJobStatus] error', { jobId, newStatus, error: msg })
        throw e
      })
  },

  // Reorder job
  reorderJob(
    jobId: string,
    beforeId?: string,
    afterId?: string,
    status?: string,
  ): Promise<z.infer<typeof schemas.KanbanSuccessResponse>> {
    // Defensive guards to avoid self-referencing or contradictory hints
    if (beforeId && beforeId === jobId) {
      debugLog('[jobService.reorderJob] adjusted beforeId equals jobId, clearing beforeId', {
        jobId,
        beforeId,
        afterId,
        status,
      })
      beforeId = undefined
    }
    if (afterId && afterId === jobId) {
      debugLog('[jobService.reorderJob] adjusted afterId equals jobId, clearing afterId', {
        jobId,
        beforeId,
        afterId,
        status,
      })
      afterId = undefined
    }
    if (beforeId && afterId && beforeId === afterId) {
      debugLog('[jobService.reorderJob] beforeId === afterId, clearing afterId', {
        jobId,
        beforeId,
        afterId,
        status,
      })
      afterId = undefined
    }

    const payload: JobReorderPayload = {}
    if (beforeId) payload.before_id = beforeId
    if (afterId) payload.after_id = afterId
    if (status) payload.status = status

    debugLog('[jobService.reorderJob] ->', { jobId, payload })
    return api
      .job_api_jobs_reorder_create(payload, { params: { job_id: jobId } })
      .then((r) => {
        debugLog('[jobService.reorderJob] ok', { jobId })
        return r
      })
      .catch((e) => {
        const msg = e instanceof Error ? e.message : String(e)
        debugLog('[jobService.reorderJob] error', { jobId, payload, error: msg })
        throw e
      })
  },

  // Add job event
  async addJobEvent(jobId: string, description: string): Promise<unknown> {
    try {
      const response = await api.job_rest_jobs_events_create(
        { description },
        { params: { job_id: jobId } },
      )

      return response
    } catch (error) {
      console.error('Error adding job event:', error)
      throw error
    }
  },

  // Upload job files
  // Note: Using axios directly because openapi-zod-client incorrectly maps format: binary
  // to z.string().url() instead of z.instanceof(File). The generator doesn't properly
  // handle multipart/form-data file uploads. This is a known limitation.
  async uploadJobFiles(
    jobId: string,
    files: File[],
  ): Promise<z.infer<typeof schemas.JobFileUploadSuccessResponse>> {
    try {
      const formData = new FormData()
      files.forEach((file) => {
        formData.append('files', file)
      })

      // Use axios directly to bypass incorrect Zod validation
      const response = await axios.post(`/job/rest/jobs/${jobId}/files/`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      return schemas.JobFileUploadSuccessResponse.parse(response.data)
    } catch (error) {
      console.error('Error uploading job files:', error)
      if (axios.isAxiosError(error) && error.response) {
        console.error('Response data:', error.response.data)
        console.error('Response status:', error.response.status)
      }
      throw error
    }
  },

  // Delete job file
  async deleteJobFile(
    jobId: string,
    fileId: string,
  ): Promise<{ success: boolean; error?: string }> {
    try {
      await api.deleteJobFile(undefined, {
        params: { job_id: jobId, file_id: fileId },
      })
      return { success: true }
    } catch (error) {
      console.error('Error deleting job file:', error)
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to delete file',
      }
    }
  },

  // Update job file metadata
  async updateJobFile(
    jobId: string,
    fileId: string,
    updates: { filename: string; print_on_jobsheet?: boolean; mime_type?: string },
  ): Promise<{ success: boolean; error?: string }> {
    try {
      const payload: JobFileRequest = {
        id: fileId,
        filename: updates.filename,
        ...(updates.mime_type ? { mime_type: updates.mime_type } : {}),
        ...(typeof updates.print_on_jobsheet === 'boolean'
          ? { print_on_jobsheet: updates.print_on_jobsheet }
          : {}),
      }

      await api.updateJobFile(payload, {
        params: { job_id: jobId, file_id: fileId },
      })

      return { success: true }
    } catch (error) {
      console.error('Error updating job file:', error)
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to update file',
      }
    }
  },
}

export default jobService
