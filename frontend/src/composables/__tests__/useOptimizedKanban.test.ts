import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const {
  route,
  replaceMock,
  setCurrentContext,
  setLoadingKanban,
  getJobsByColumn,
  performAdvancedSearch,
} = vi.hoisted(() => ({
  route: { query: {} as Record<string, string> },
  replaceMock: vi.fn(),
  setCurrentContext: vi.fn(),
  setLoadingKanban: vi.fn(),
  getJobsByColumn: vi.fn(),
  performAdvancedSearch: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ replace: replaceMock }),
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
  },
}))

vi.mock('@/stores/jobs', () => ({
  useJobsStore: () => ({
    setCurrentContext,
    setLoadingKanban,
  }),
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

import { useOptimizedKanban } from '../useOptimizedKanban'

type HarnessState = ReturnType<typeof useOptimizedKanban>

function buildKanbanJob(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: overrides.id ?? 'job-1',
    name: overrides.name ?? '2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)',
    description: overrides.description ?? '',
    job_number: overrides.job_number ?? 9001,
    client_name: overrides.client_name ?? 'Weaver, Decker and Schultz',
    contact_person: overrides.contact_person ?? 'Molly Wainwright',
    people: overrides.people ?? [],
    status: overrides.status ?? 'in_progress',
    status_key: overrides.status_key ?? 'in_progress',
    rejected_flag: false,
    paid: false,
    fully_invoiced: false,
    speed_quality_tradeoff: 'balanced',
    created_by_id: null,
    created_at: null,
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

  it('shows immediate local matches, then reconciles with backend results', async () => {
    performAdvancedSearch.mockResolvedValue({
      jobs: [
        buildKanbanJob({ id: 'job-1' }),
        buildKanbanJob({
          id: 'job-2',
          name: 'Kick plate revision',
          client_name: 'Different Client',
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
      client_name: '',
      contact_person: '',
      created_by: '',
      created_after: '',
      created_before: '',
      paid: '',
      rejected_flag: '',
      xero_invoice_params: '',
    })
    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-1', 'job-2'])
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
      jobs: [buildKanbanJob({ id: 'job-2', client_name: 'Weaver, Decker and Schultz' })],
    })
    await flushPromises()

    first.resolve({
      jobs: [buildKanbanJob({ id: 'job-stale', name: 'Stale job' })],
    })
    await flushPromises()

    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-2'])
  })

  it('uses backend reconciliation for multi-token queries the local substring pass cannot match', async () => {
    performAdvancedSearch.mockResolvedValue({
      jobs: [buildKanbanJob({ id: 'job-2', client_name: 'Weaver, Decker and Schultz' })],
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
      client_name: '',
      contact_person: '',
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
      jobs: [buildKanbanJob({ id: 'job-3', client_name: 'Weaver, Decker and Schultz' })],
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
      client_name: '',
      contact_person: '',
      created_by: '',
      created_after: '',
      created_before: '',
      paid: '',
      rejected_flag: '',
      xero_invoice_params: '',
    })
    expect(kanban.filteredJobs.value.map((job) => job.id)).toEqual(['job-3'])
  })
})
