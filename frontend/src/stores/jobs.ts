import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { schemas } from '../api/generated/api'
import { debugLog } from '../utils/debug'
import type { z } from 'zod'
import { api } from '../api/client'
import { jobService } from '../services/job.service'

type Job = z.infer<typeof schemas.Job>
type JobDetail = z.infer<typeof schemas.JobDetailResponse>['data']

// Basic info fields that are stored separately to prevent autosave conflicts
type JobBasicInfo = z.infer<typeof schemas.JobBasicInformationResponse>
type JobEvent = z.infer<typeof schemas.JobEvent>
type KanbanJobUI = z.infer<typeof schemas.KanbanJob>
type CompanyDefaultsJobDetail = z.infer<typeof schemas.CompanyDefaultsJobDetail>
type JobHeaderResponse = z.infer<typeof schemas.JobHeaderResponse>

export const useJobsStore = defineStore('jobs', () => {
  const detailedJobs = ref<Record<string, JobDetail>>({})
  const kanbanJobs = ref<Record<string, KanbanJobUI>>({})
  const headersById = ref<Record<string, JobHeaderResponse>>({})
  const basicInfoById = ref<Record<string, JobBasicInfo>>({})
  // Conflict reload timestamp per jobId for UI sync (JobView / JobSettings)
  const conflictReloadAtById = ref<Record<string, number>>({})
  const isLoadingJob = ref(false)
  const isLoadingKanban = ref(false)
  const currentContext = ref<'kanban' | 'detail' | null>(null)

  const allKanbanJobs = computed(() => {
    return Object.values(kanbanJobs.value)
  })

  const getJobById = computed(() => {
    return (id: string): JobDetail | null => {
      return detailedJobs.value[id] || null
    }
  })

  const getKanbanJobById = computed(() => {
    return (id: string): KanbanJobUI | null => {
      return kanbanJobs.value[id] || null
    }
  })

  const getHeaderById = computed(() => {
    return (id: string): JobHeaderResponse | null => {
      return headersById.value[id] || null
    }
  })

  const getBasicInfoById = computed(() => {
    return (id: string): JobBasicInfo | null => {
      return basicInfoById.value[id] || null
    }
  })

  const setDetailedJob = (jobDetail: JobDetail): void => {
    if (!jobDetail) {
      debugLog('Store - setDetailedJob called with null/undefined jobDetail')
      return
    }

    // JobDetail has structure: {job: {...}, events: [...], company_defaults: {...}}
    if (!jobDetail.job || !jobDetail.job.id || typeof jobDetail.job.id !== 'string') {
      debugLog('Store - setDetailedJob called with invalid jobDetail structure:', {
        hasJob: !!jobDetail.job,
        jobId: jobDetail.job?.id,
        jobIdType: typeof jobDetail.job?.id,
      })
      return
    }

    const jobId = jobDetail.job.id
    const existingJob = detailedJobs.value[jobId]

    // Preserve existing basic info fields if they're not present in the new data
    const mergedJobDetail = { ...jobDetail }
    if (existingJob && existingJob.job) {
      mergedJobDetail.job = {
        ...existingJob.job, // Start with existing data
        ...jobDetail.job, // Override with new data
        // Preserve basic info fields if not present in new data
        description: jobDetail.job.description ?? existingJob.job.description,
        order_number: jobDetail.job.order_number ?? existingJob.job.order_number,
        notes: jobDetail.job.notes ?? existingJob.job.notes,
        delivery_date: jobDetail.job.delivery_date ?? existingJob.job.delivery_date,
      }
      // Preserve other arrays/objects if not present
      mergedJobDetail.events = jobDetail.events ?? existingJob.events
      mergedJobDetail.company_defaults = jobDetail.company_defaults ?? existingJob.company_defaults
    }

    if (existingJob && JSON.stringify(existingJob) === JSON.stringify(mergedJobDetail)) {
      debugLog('Store - JobDetail data identical, skipping update to prevent loop:', jobId)
      return
    }

    debugLog('Store - setDetailedJob called:', {
      jobId,
      jobStatus: mergedJobDetail.job.job_status,
      hasEvents: Array.isArray(mergedJobDetail.events),
      eventsCount: mergedJobDetail.events?.length || 0,
      preservedBasicInfo: !!existingJob,
    })

    detailedJobs.value = {
      ...detailedJobs.value,
      [jobId]: mergedJobDetail,
    }

    debugLog('Store - Job updated successfully:', {
      jobId,
      newStatus: detailedJobs.value[jobId]?.job?.job_status,
    })

    // Always keep header in sync when receiving full job
    setHeader(jobToHeader(mergedJobDetail.job))

    if (kanbanJobs.value[jobId]) {
      debugLog('Store - Also updating kanban job')
      updateKanbanJobFromDetailed(mergedJobDetail)
    }
  }

  const updateDetailedJob = (jobId: string, updates: Partial<JobDetail>): void => {
    const existingJob = detailedJobs.value[jobId]
    if (existingJob) {
      const updatedJob = { ...existingJob, ...updates }
      detailedJobs.value = {
        ...detailedJobs.value,
        [jobId]: updatedJob,
      }

      if (kanbanJobs.value[jobId]) {
        updateKanbanJobFromDetailed(updatedJob)
      }
    }
  }

  const removeDetailedJob = (jobId: string): void => {
    delete detailedJobs.value[jobId]
  }

  const setKanbanJobs = (jobs: KanbanJobUI[]): void => {
    kanbanJobs.value = {}
    jobs.forEach((job) => {
      kanbanJobs.value[job.id] = job
    })
  }

  const setKanbanJob = (job: KanbanJobUI): void => {
    kanbanJobs.value[job.id] = job
  }

  const updateKanbanJob = (jobId: string, updates: Partial<KanbanJobUI>): void => {
    const existingJob = kanbanJobs.value[jobId]
    if (existingJob) {
      kanbanJobs.value[jobId] = { ...existingJob, ...updates }
    }
  }

  const removeKanbanJob = (jobId: string): void => {
    delete kanbanJobs.value[jobId]
  }

  const updateKanbanJobFromDetailed = (detailedJob: JobDetail): void => {
    const jobId = detailedJob.job.id
    const kanbanJob = kanbanJobs.value[jobId]
    if (kanbanJob) {
      kanbanJobs.value[jobId] = {
        ...kanbanJob,
        name: detailedJob.job.name,
        status: detailedJob.job.job_status,
        client_name: detailedJob.job.client_name || '',
        contact_person: detailedJob.job.contact_name || kanbanJob.contact_person,
        paid: detailedJob.job.paid || false,
      }
    }
  }

  const setCurrentContext = (context: 'kanban' | 'detail' | null): void => {
    currentContext.value = context
  }

  const setLoadingJob = (loading: boolean): void => {
    isLoadingJob.value = loading
  }

  const setLoadingKanban = (loading: boolean): void => {
    isLoadingKanban.value = loading
  }

  const clearDetailedJobs = (): void => {
    detailedJobs.value = {}
  }

  const clearKanbanJobs = (): void => {
    kanbanJobs.value = {}
  }

  const clearAll = (): void => {
    clearDetailedJobs()
    clearKanbanJobs()
    basicInfoById.value = {}
    currentContext.value = null
  }

  const setBasicInfo = (jobId: string, basicInfo: JobBasicInfo): void => {
    // Immutable update to guarantee reactivity for consumers
    basicInfoById.value = {
      ...basicInfoById.value,
      [jobId]: basicInfo,
    }
  }

  const updateBasicInfo = (jobId: string, updates: Partial<JobBasicInfo>): void => {
    const existing = basicInfoById.value[jobId]
    if (existing) {
      // Immutable update to guarantee reactivity
      basicInfoById.value = {
        ...basicInfoById.value,
        [jobId]: { ...existing, ...updates },
      }
    }
  }

  const commitJobBasicInfoFromServer = (jobId: string, payload: Partial<JobBasicInfo>): void => {
    if (!jobId || !payload) return

    const sanitized: Partial<JobBasicInfo> = {}

    if ('description' in payload) {
      sanitized.description = payload.description ?? null
    }
    if ('delivery_date' in payload) {
      sanitized.delivery_date = payload.delivery_date ?? null
    }
    if ('order_number' in payload) {
      sanitized.order_number = payload.order_number ?? null
    }
    if ('notes' in payload) {
      sanitized.notes = payload.notes ?? null
    }

    if (Object.keys(sanitized).length === 0) return

    const existing = basicInfoById.value[jobId]
    basicInfoById.value = {
      ...basicInfoById.value,
      [jobId]: {
        ...(existing ?? ({} as JobBasicInfo)),
        ...sanitized,
      },
    }

    const detail = detailedJobs.value[jobId]
    if (detail) {
      detailedJobs.value = {
        ...detailedJobs.value,
        [jobId]: {
          ...detail,
          job: {
            ...detail.job,
            ...sanitized,
          },
        },
      }
    }
  }

  const loadBasicInfo = async (jobId: string): Promise<JobBasicInfo | null> => {
    try {
      const data = await api.job_rest_jobs_basic_info_retrieve({
        params: { job_id: jobId },
      })

      debugLog('Store - loadBasicInfo success:', { jobId, data })
      setBasicInfo(jobId, data)
      return data
    } catch (error) {
      debugLog('Store - loadBasicInfo error:', error)
      throw error
    }
  }

  const updateJobStatus = (jobId: string, newStatus: string): void => {
    const existingJob = detailedJobs.value[jobId]
    if (existingJob) {
      updateDetailedJob(jobId, {
        job: { ...existingJob.job, job_status: newStatus },
      })
    }

    updateKanbanJob(jobId, { status: newStatus })
  }

  const updateJobEvents = (jobId: string, events: JobEvent[]): void => {
    const job = detailedJobs.value[jobId]
    if (job) {
      detailedJobs.value[jobId] = { ...job, events }
    }
  }

  const addJobEvent = (jobId: string, event: JobEvent): void => {
    const job = detailedJobs.value[jobId]
    if (job) {
      const events = job.events || []
      detailedJobs.value[jobId] = { ...job, events: [event, ...events] }
    }
  }

  const updateJobCompanyDefaults = (
    jobId: string,
    companyDefaults: CompanyDefaultsJobDetail,
  ): void => {
    const jobDetail = detailedJobs.value[jobId]
    if (jobDetail) {
      detailedJobs.value[jobId] = { ...jobDetail, company_defaults: companyDefaults }
    }
  }

  const updateJobPartialData = (jobId: string, partialData: Partial<JobDetail>): void => {
    const jobDetail = detailedJobs.value[jobId]
    if (jobDetail) {
      detailedJobs.value[jobId] = { ...jobDetail, ...partialData }

      if (kanbanJobs.value[jobId]) {
        updateKanbanJobFromDetailed(detailedJobs.value[jobId])
      }
    }
  }

  const jobToHeader = (job: Job): JobHeaderResponse => {
    return {
      job_id: job.id,
      job_number: job.job_number,
      name: job.name,
      client_id: job.client_id ?? null,
      client_name: job.client_name ?? null,
      contact_id: job.contact_id ?? null,
      contact_name: job.contact_name ?? null,
      status: job.job_status as JobHeaderResponse['status'],
      pricing_methodology: job.pricing_methodology ?? undefined,
      fully_invoiced: job.fully_invoiced,
      quoted: job.quoted,
      quote_acceptance_date: job.quote_acceptance_date ?? null,
      paid: Boolean(job.paid),
      price_cap: job.price_cap ?? null,
      default_xero_pay_item_id: job.default_xero_pay_item_id ?? null,
      default_xero_pay_item_name: job.default_xero_pay_item_name ?? null,
    }
  }

  const setHeader = (header: JobHeaderResponse): void => {
    // Immutable update to guarantee reactivity of consumers (e.g., JobView header)
    headersById.value = {
      ...headersById.value,
      [header.job_id]: header,
    }
  }

  const patchHeader = (jobId: string, patch: Partial<JobHeaderResponse>): void => {
    const cur = headersById.value[jobId]
    if (!cur) return
    // Immutable update to force dependent computeds/watchers to re-run
    headersById.value = {
      ...headersById.value,
      [jobId]: { ...cur, ...patch },
    }
  }

  const upsertFromFullJob = (job: Job): void => {
    setHeader(jobToHeader(job))
  }

  async function fetchJob(jobId: string): Promise<unknown> {
    if (!jobId) return undefined

    try {
      const response = await jobService.getJob(jobId)

      if (response.success && response.data) {
        setDetailedJob(response.data)
        return { job: response.data.job, events: response.data.events || [] }
      }

      throw new Error('Job not found or invalid response format')
    } catch (error) {
      debugLog('Store - fetchJob error:', error)
      throw error
    }
  }

  /**
   * Reloads job data when a concurrency conflict occurs.
   * This fetches fresh data from the server to get the latest ETag and job state.
   * @param jobId - The job ID to reload
   */
  async function reloadJobOnConflict(jobId: string): Promise<void> {
    debugLog('Store - reloadJobOnConflict called:', { jobId })

    try {
      // 1) Fetch full job detail (captures new ETag via interceptor and updates detailed + header)
      await fetchJob(jobId)

      // 2) Also fetch the lightweight header directly to guarantee the latest name/status/etc.
      //    This ensures views bound to headersById reflect backend changes immediately.
      try {
        const headerResponse = await api.job_rest_jobs_header_retrieve({
          params: { job_id: jobId },
        })
        setHeader(headerResponse)
        debugLog('Store - header refreshed after conflict:', {
          jobId,
          name: headerResponse.name,
          status: headerResponse.status,
        })
      } catch (headerErr) {
        debugLog('Store - header refresh failed after conflict (will rely on full job):', {
          jobId,
          error: headerErr,
        })
      }

      // 3) Refresh Basic Info to reflect immediately in JobSettingsTab
      try {
        const bi = await api.job_rest_jobs_basic_info_retrieve({
          params: { job_id: jobId },
        })
        setBasicInfo(jobId, bi)
        debugLog('Store - basic info refreshed after conflict:', {
          jobId,
          hasDescription: !!bi.description,
        })
      } catch (biErr) {
        debugLog('Store - basic info refresh failed after conflict:', { jobId, error: biErr })
      }

      // 4) Mark conflict reload timestamp so components can force local sync
      conflictReloadAtById.value = {
        ...conflictReloadAtById.value,
        [jobId]: Date.now(),
      }

      debugLog('Store - reloadJobOnConflict success:', { jobId })
    } catch (error) {
      debugLog('Store - reloadJobOnConflict error:', { jobId, error })
      throw error
    }
  }

  return {
    detailedJobs,
    kanbanJobs,
    headersById,
    basicInfoById,
    isLoadingJob,
    isLoadingKanban,
    currentContext,

    allKanbanJobs,
    getJobById,
    getKanbanJobById,
    getHeaderById,
    getBasicInfoById,
    conflictReloadAtById,

    setDetailedJob,
    updateDetailedJob,
    removeDetailedJob,
    setKanbanJobs,
    setKanbanJob,
    updateKanbanJob,
    removeKanbanJob,
    setCurrentContext,
    setLoadingJob,
    setLoadingKanban,
    clearDetailedJobs,
    clearKanbanJobs,

    clearAll,
    updateJobStatus,
    updateJobEvents,
    addJobEvent,
    updateJobCompanyDefaults,
    updateJobPartialData,

    setBasicInfo,
    updateBasicInfo,
    commitJobBasicInfoFromServer,
    loadBasicInfo,

    jobToHeader,
    setHeader,
    patchHeader,
    upsertFromFullJob,

    fetchJob,
    reloadJobOnConflict,
  }
})
