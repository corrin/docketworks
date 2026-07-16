import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const {
  route,
  pushMock,
  replaceMock,
  setCurrentContext,
  setLoadingKanban,
  getJobsByColumn,
  updateJobStatus,
  reorderJob,
  performAdvancedSearch,
  checkFreshness,
  saveFeedback,
  kanbanColumnCache,
  kanbanJobsById,
  logSearchResultClick,
} = vi.hoisted(() => ({
  route: { query: {} as Record<string, string> },
  pushMock: vi.fn(),
  replaceMock: vi.fn(),
  setCurrentContext: vi.fn(),
  setLoadingKanban: vi.fn(),
  getJobsByColumn: vi.fn(),
  updateJobStatus: vi.fn(),
  reorderJob: vi.fn(),
  performAdvancedSearch: vi.fn(),
  checkFreshness: vi.fn(),
  saveFeedback: {
    pending: vi.fn(),
    saving: vi.fn(),
    saved: vi.fn(),
    error: vi.fn(),
    clear: vi.fn(),
  },
  kanbanColumnCache: new Map<string, unknown>(),
  kanbanJobsById: new Map<string, Record<string, unknown>>(),
  logSearchResultClick: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
}))

vi.mock('@/services/searchTelemetry.service', () => ({
  logSearchResultClick,
}))

vi.mock('@/services/job.service', () => ({
  jobService: {
    getJobsByColumn,
    getStatusChoices: vi.fn().mockResolvedValue({
      success: true,
      statuses: {
        draft: 'Draft',
        in_progress: 'In Progress',
        archived: 'Archived',
      },
      tooltips: {},
    }),
    performAdvancedSearch,
    updateJobStatus,
    reorderJob,
  },
}))

vi.mock('@/stores/jobs', () => ({
  useJobsStore: () => ({
    kanbanCacheGeneration: 0,
    getKanbanColumnCache: (columnId: string) => kanbanColumnCache.get(columnId) ?? null,
    getKanbanColumnJobs: (columnId: string) => {
      const cached = kanbanColumnCache.get(columnId) as { jobIds?: string[] } | undefined
      if (!cached) return null
      const jobs = (cached.jobIds ?? [])
        .map((jobId) => kanbanJobsById.get(jobId) ?? null)
        .filter((job): job is Record<string, unknown> => job !== null)
      return jobs.length === (cached.jobIds ?? []).length ? jobs : null
    },
    hasKanbanColumnCache: (columnId: string) => kanbanColumnCache.has(columnId),
    getKanbanJobById: (jobId: string) => kanbanJobsById.get(jobId) ?? null,
    loadKanbanColumnWithCache: async (
      columnId: string,
      load: () => Promise<unknown>,
      options: { force?: boolean } = {},
    ) => {
      if (!options.force && kanbanColumnCache.has(columnId)) {
        return kanbanColumnCache.get(columnId)
      }
      const response = (await load()) as { jobs?: Record<string, unknown>[] }
      const jobs = response.jobs ?? []
      jobs.forEach((job) => kanbanJobsById.set(String(job.id), job))
      const cached = {
        ...response,
        jobs: undefined,
        jobIds: jobs.map((job) => String(job.id)),
      }
      kanbanColumnCache.set(columnId, cached)
      return cached
    },
    updateKanbanJob: (jobId: string, updates: Record<string, unknown>) => {
      const existing = kanbanJobsById.get(jobId)
      if (existing) {
        kanbanJobsById.set(jobId, { ...existing, ...updates })
      }
    },
    moveKanbanJobInColumnCache: (
      jobId: string,
      sourceColumnId: string,
      targetColumnId: string,
      anchorJobId?: string,
      placement?: 'above' | 'below',
    ) => {
      const sourceCache = kanbanColumnCache.get(sourceColumnId) as { jobIds?: string[] } | undefined
      if (sourceCache) {
        sourceCache.jobIds = (sourceCache.jobIds ?? []).filter(
          (cachedJobId) => cachedJobId !== jobId,
        )
      }

      const targetCache = kanbanColumnCache.get(targetColumnId) as { jobIds?: string[] } | undefined
      if (targetCache) {
        const withoutMovedJob = (targetCache.jobIds ?? []).filter(
          (cachedJobId) => cachedJobId !== jobId,
        )
        let insertIndex = 0
        if (anchorJobId && placement) {
          const anchorIndex = withoutMovedJob.indexOf(anchorJobId)
          if (anchorIndex !== -1) {
            insertIndex = placement === 'above' ? anchorIndex : anchorIndex + 1
          } else {
            kanbanColumnCache.delete(targetColumnId)
            return
          }
        }
        withoutMovedJob.splice(insertIndex, 0, jobId)
        targetCache.jobIds = withoutMovedJob
      }
    },
    setCurrentContext,
    setLoadingKanban,
  }),
}))

vi.mock('../useDataFreshness', () => ({
  dataFreshness: {
    checkFreshness,
  },
}))

vi.mock('@/services/kanban-categorization.service', () => ({
  KanbanCategorizationService: {
    getAllColumns: () => [
      { columnId: 'draft', statusKey: 'draft', columnTitle: 'Draft' },
      { columnId: 'in_progress', statusKey: 'in_progress', columnTitle: 'In Progress' },
      { columnId: 'archived', statusKey: 'archived', columnTitle: 'Archived' },
    ],
    getColumnForStatus: (status: string) => status,
  },
}))

vi.mock('@/api/generated/api', () => ({
  schemas: {},
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('@/composables/useSaveFeedback', () => ({
  useSaveFeedback: () => saveFeedback,
}))

import { useOptimizedKanban } from '../useOptimizedKanban'
import { debugLog } from '@/utils/debug'

type HarnessState = ReturnType<typeof useOptimizedKanban>

function buildKanbanJob(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: overrides.id ?? 'job-1',
    name: overrides.name ?? '2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)',
    description: overrides.description ?? '',
    job_number: overrides.job_number ?? 9001,
    company_name: overrides.company_name ?? 'Weaver, Decker and Schultz',
    person_name: overrides.person_name ?? 'Molly Wainwright',
    people: overrides.people ?? [],
    status: overrides.status ?? 'in_progress',
    status_key: overrides.status_key ?? 'in_progress',
    rejected_flag: false,
    paid: false,
    fully_invoiced: false,
    speed_quality_tradeoff: 'balanced',
    created_by_id: null,
    created_at: null,
    updated_at: overrides.updated_at ?? '2026-05-14T00:00:00Z',
    delivery_date: null,
    priority: 100,
    shop_job: false,
    over_budget: false,
    quote_revenue: 0,
    time_and_materials_revenue: 0,
    min_people: 1,
    max_people: 1,
    badge_label: 'In Progress',
    badge_color: 'bg-blue-500',
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function mountHarness() {
  let exposed!: HarnessState
  const Harness = defineComponent({
    setup() {
      exposed = useOptimizedKanban()
      return () => null
    },
  })

  mount(Harness)
  await flushPromises()
  return exposed
}

describe('useOptimizedKanban search reconciliation', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    route.query = {}
    kanbanColumnCache.clear()
    kanbanJobsById.clear()
    checkFreshness.mockResolvedValue(undefined)
    updateJobStatus.mockResolvedValue({ success: true })
    reorderJob.mockResolvedValue({ success: true })
    getJobsByColumn.mockImplementation(async (columnId: string) => {
      if (columnId === 'in_progress') {
        return {
          success: true,
          jobs: [buildKanbanJob()],
          total: 1,
          filtered_count: 1,
          has_more: false,
        }
      }
      return { success: true, jobs: [], total: 0, filtered_count: 0, has_more: false }
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts loading columns during setup before mounted work settles', () => {
    const Harness = defineComponent({
      setup() {
        useOptimizedKanban()
        return () => null
      },
    })

    mount(Harness)

    expect(getJobsByColumn).toHaveBeenCalledWith('draft')
    expect(getJobsByColumn).toHaveBeenCalledWith('in_progress')
    expect(getJobsByColumn).toHaveBeenCalledWith('archived')
  })

  it('hydrates cached columns without refetching them', async () => {
    const cachedJob = buildKanbanJob()
    kanbanJobsById.set(cachedJob.id, cachedJob)
    kanbanColumnCache.set('draft', {
      success: true,
      jobIds: [],
      total: 0,
      filtered_count: 0,
      has_more: false,
    })
    kanbanColumnCache.set('in_progress', {
      success: true,
      jobIds: [cachedJob.id],
      total: 1,
      filtered_count: 1,
      has_more: false,
    })
    kanbanColumnCache.set('archived', {
      success: true,
      jobIds: [],
      total: 0,
      filtered_count: 0,
      has_more: false,
    })

    const kanban = await mountHarness()

    expect(getJobsByColumn).not.toHaveBeenCalled()
    expect(checkFreshness).toHaveBeenCalledOnce()
    expect(kanban.getJobsByStatus.value('in_progress').map((job) => job.id)).toEqual(['job-1'])
  })

  it('shows immediate local matches, then reconciles with backend results', async () => {
    performAdvancedSearch.mockResolvedValue({
      jobs: [
        buildKanbanJob({ id: 'job-1' }),
        buildKanbanJob({
          id: 'job-2',
          name: 'Kick plate revision',
          company_name: 'Different Company',
        }),
      ],
    })

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'kick'
    await kanban.handleSearch()

    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-1'])
    expect(performAdvancedSearch).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(performAdvancedSearch).toHaveBeenCalledWith({
      q: 'kick',
      status: [],
      job_number: '',
      name: '',
      description: '',
      company_name: '',
      person_name: '',
      created_by: '',
      created_after: '',
      created_before: '',
      paid: '',
      rejected_flag: '',
      xero_invoice_params: '',
    })
    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-1', 'job-2'])
  })

  it('renders filtered kanban columns by priority order after backend search reconciliation', async () => {
    performAdvancedSearch.mockResolvedValue({
      jobs: [
        buildKanbanJob({
          id: 'job-96990',
          job_number: 96990,
          status: 'approved',
          status_key: 'approved',
          priority: 5600,
          created_at: '2026-04-22T21:54:41Z',
        }),
        buildKanbanJob({
          id: 'job-96477',
          job_number: 96477,
          status: 'approved',
          status_key: 'approved',
          priority: 5800,
          created_at: '2025-12-10T23:47:12Z',
        }),
      ],
    })

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'Mayer'
    await kanban.handleSearch()
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-96477', 'job-96990'])
    expect(kanban.getJobsByStatus.value('approved').map((job) => job.id)).toEqual([
      'job-96477',
      'job-96990',
    ])
    expect(debugLog).toHaveBeenCalledWith(
      'kanban.search.reconciled-order',
      expect.objectContaining({
        query: 'Mayer',
        rawOrder: expect.arrayContaining([
          expect.objectContaining({ jobNumber: 96990, priority: 5600 }),
          expect.objectContaining({ jobNumber: 96477, priority: 5800 }),
        ]),
        renderedColumnOrder: expect.objectContaining({
          approved: [
            expect.objectContaining({ jobNumber: 96477, priority: 5800 }),
            expect.objectContaining({ jobNumber: 96990, priority: 5600 }),
          ],
        }),
      }),
    )
  })

  it('logs a search-result click before navigating to the job', async () => {
    performAdvancedSearch.mockResolvedValue({
      jobs: [buildKanbanJob({ id: 'job-search', job_number: 9010, name: 'Search Job' })],
    })

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'search'
    await kanban.handleSearch()
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    kanban.viewJob(kanban.filteredJobs.value[0])

    expect(logSearchResultClick).toHaveBeenCalledWith(
      expect.objectContaining({
        domain: 'kanban',
        query: 'search',
        selectedResultId: 'job-search',
        selectedLabel: '#9010 Search Job',
        selectedRank: 1,
        resultCount: 1,
        source: 'kanban_quick_search',
      }),
    )
    expect(pushMock).toHaveBeenCalledWith('/jobs/job-search')
  })

  it('ignores stale backend responses when the user keeps typing', async () => {
    const first = deferred<{ jobs: ReturnType<typeof buildKanbanJob>[] }>()
    const second = deferred<{ jobs: ReturnType<typeof buildKanbanJob>[] }>()
    performAdvancedSearch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'kick'
    await kanban.handleSearch()
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    kanban.searchQuery.value = 'weaver'
    await kanban.handleSearch()
    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-1'])

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    second.resolve({
      jobs: [buildKanbanJob({ id: 'job-2', company_name: 'Weaver, Decker and Schultz' })],
    })
    await flushPromises()

    first.resolve({
      jobs: [buildKanbanJob({ id: 'job-stale', name: 'Stale job' })],
    })
    await flushPromises()

    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-2'])
  })

  it('keeps loading false when a pending backend search is cleared before debounce fires', async () => {
    performAdvancedSearch.mockResolvedValue({
      jobs: [buildKanbanJob({ id: 'job-2', name: 'Kick plate revision' })],
    })

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'kick'
    await kanban.handleSearch()

    kanban.searchQuery.value = ''
    await kanban.handleSearch()

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(performAdvancedSearch).not.toHaveBeenCalled()
    expect(kanban.isLoading.value).toBe(false)
    expect(kanban.filteredJobs.value).toEqual([])
  })

  it('uses backend reconciliation for multi-token queries the local substring pass cannot match', async () => {
    performAdvancedSearch.mockResolvedValue({
      jobs: [buildKanbanJob({ id: 'job-2', company_name: 'Weaver, Decker and Schultz' })],
    })

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'weaver schultz'
    await kanban.handleSearch()

    expect(kanban.filteredJobs.value).toEqual([])

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(performAdvancedSearch).toHaveBeenCalledWith({
      q: 'weaver schultz',
      status: [],
      job_number: '',
      name: '',
      description: '',
      company_name: '',
      person_name: '',
      created_by: '',
      created_after: '',
      created_before: '',
      paid: '',
      rejected_flag: '',
      xero_invoice_params: '',
    })
    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-2'])
  })

  it('reconciles typo queries from empty local results to backend matches', async () => {
    performAdvancedSearch.mockResolvedValue({
      jobs: [buildKanbanJob({ id: 'job-3', company_name: 'Weaver, Decker and Schultz' })],
    })

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'weavr schultzz'
    await kanban.handleSearch()

    expect(kanban.filteredJobs.value).toEqual([])

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(performAdvancedSearch).toHaveBeenCalledWith({
      q: 'weavr schultzz',
      status: [],
      job_number: '',
      name: '',
      description: '',
      company_name: '',
      person_name: '',
      created_by: '',
      created_after: '',
      created_before: '',
      paid: '',
      rejected_flag: '',
      xero_invoice_params: '',
    })
    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-3'])
  })

  it('moves a job locally between columns before status update revalidation completes', async () => {
    const pendingStatusUpdate = deferred<{ success: boolean }>()
    updateJobStatus.mockReturnValueOnce(pendingStatusUpdate.promise)

    const kanban = await mountHarness()

    const updatePromise = kanban.updateJobStatus('job-1', 'draft')

    expect(kanban.getJobsByStatus.value('in_progress').map((job) => job.id)).toEqual([])
    expect(kanban.getJobsByStatus.value('draft').map((job) => job.id)).toEqual(['job-1'])

    pendingStatusUpdate.resolve({ success: true })
    await updatePromise
  })

  it('keeps a filtered single visible job visible in its new column after a drag status update', async () => {
    const pendingStatusUpdate = deferred<{ success: boolean }>()
    updateJobStatus.mockReturnValueOnce(pendingStatusUpdate.promise)

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'kick'
    await kanban.handleSearch()

    expect(kanban.getJobsByStatus.value('in_progress').map((job) => job.id)).toEqual(['job-1'])

    const updatePromise = kanban.updateJobStatus('job-1', 'draft')

    expect(kanban.getJobsByStatus.value('in_progress').map((job) => job.id)).toEqual([])
    expect(kanban.getJobsByStatus.value('draft').map((job) => job.id)).toEqual(['job-1'])
    expect(kanban.filteredJobs.value).toMatchObject([{ id: 'job-1', status: 'draft' }])

    pendingStatusUpdate.resolve({ success: true })
    await updatePromise
  })

  it('keeps a same-column reordered job visible before reorder revalidation completes', async () => {
    const pendingReorder = deferred<{ success: boolean }>()
    reorderJob.mockReturnValueOnce(pendingReorder.promise)
    const secondJob = buildKanbanJob({ id: 'job-2', job_number: 9002 })
    getJobsByColumn.mockImplementation(async (columnId: string) => {
      if (columnId === 'in_progress') {
        return {
          success: true,
          jobs: [buildKanbanJob(), secondJob],
          total: 2,
          filtered_count: 2,
          has_more: false,
        }
      }
      return { success: true, jobs: [], total: 0, filtered_count: 0, has_more: false }
    })

    const kanban = await mountHarness()

    const reorderPromise = kanban.reorderJob('job-1', 'job-2', 'below', 'in_progress')

    expect(kanban.getJobsByStatus.value('in_progress').map((job) => job.id)).toEqual([
      'job-2',
      'job-1',
    ])
    expect(saveFeedback.saving).toHaveBeenCalled()

    pendingReorder.resolve({ success: true })
    await reorderPromise

    expect(saveFeedback.saved).toHaveBeenCalled()
  })

  it('moves a cross-column reorder locally and updates filtered status before persistence completes', async () => {
    const pendingReorder = deferred<{ success: boolean }>()
    reorderJob.mockReturnValueOnce(pendingReorder.promise)

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'kick'
    await kanban.handleSearch()

    const reorderPromise = kanban.reorderJob('job-1', undefined, undefined, 'draft', 'drag-123')

    expect(kanban.getJobsByStatus.value('in_progress').map((job) => job.id)).toEqual([])
    expect(kanban.getJobsByStatus.value('draft').map((job) => job.id)).toEqual(['job-1'])
    expect(kanban.filteredJobs.value).toMatchObject([
      { id: 'job-1', status: 'draft', status_key: 'draft' },
    ])

    pendingReorder.resolve({ success: true })
    await reorderPromise

    expect(getJobsByColumn).toHaveBeenCalledTimes(3)
    expect(reorderJob).toHaveBeenCalledWith('job-1', undefined, undefined, 'draft')
  })

  it('does not force column revalidation after a successful reorder persistence', async () => {
    const kanban = await mountHarness()

    await kanban.reorderJob('job-1', undefined, undefined, 'draft', 'drag-456')

    expect(getJobsByColumn).toHaveBeenCalledTimes(3)
    expect(debugLog).toHaveBeenCalledWith('kanban.drag.persist.success', {
      dragId: 'drag-456',
      jobId: 'job-1',
      revalidated: false,
    })
  })

  it('rolls back local drag state and revalidates affected columns when reorder persistence fails', async () => {
    reorderJob.mockRejectedValueOnce(new Error('nope'))

    const kanban = await mountHarness()

    await kanban.reorderJob('job-1', undefined, undefined, 'draft', 'drag-789')

    expect(kanban.getJobsByStatus.value('in_progress').map((job) => job.id)).toEqual(['job-1'])
    expect(kanban.getJobsByStatus.value('draft').map((job) => job.id)).toEqual([])
    expect(saveFeedback.error).toHaveBeenCalledWith('Job move failed. Change reverted.')
    expect(getJobsByColumn).toHaveBeenCalledTimes(5)
    expect(debugLog).toHaveBeenCalledWith(
      'kanban.drag.rollback.revalidate',
      expect.objectContaining({
        dragId: 'drag-789',
        jobId: 'job-1',
        columnIds: ['in_progress', 'draft'],
      }),
    )
  })

  it('keeps a search-only job visible after a drag status update', async () => {
    const pendingStatusUpdate = deferred<{ success: boolean }>()
    updateJobStatus.mockReturnValueOnce(pendingStatusUpdate.promise)
    performAdvancedSearch.mockResolvedValue({
      jobs: [buildKanbanJob({ id: 'job-search-only', status: 'in_progress' })],
    })

    const kanban = await mountHarness()

    kanban.searchQuery.value = 'search-only'
    await kanban.handleSearch()
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    const updatePromise = kanban.updateJobStatus('job-search-only', 'draft', {
      sourceColumnId: 'in_progress',
      targetColumnId: 'draft',
    })

    expect(kanban.getJobsByStatus.value('in_progress').map((job) => job.id)).toEqual([])
    expect(kanban.getJobsByStatus.value('draft').map((job) => job.id)).toEqual(['job-search-only'])

    pendingStatusUpdate.resolve({ success: true })
    await updatePromise
  })
})
