import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useJobsStore } from '@/stores/jobs'

vi.mock('@/api/client', () => ({
  api: {},
}))

vi.mock('@/services/job.service', () => ({
  jobService: {},
}))

vi.mock('@/composables/useDataFreshness', () => ({
  dataFreshness: {
    subscribe: vi.fn(),
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

function buildKanbanJob(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: overrides.id ?? 'job-1',
    name: overrides.name ?? 'Kanban Job',
    description: overrides.description ?? '',
    job_number: overrides.job_number ?? 9001,
    company_name: overrides.company_name ?? 'Company',
    person_name: overrides.person_name ?? '',
    people: overrides.people ?? [],
    status: overrides.status ?? 'In Progress',
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

describe('jobs store kanban cache', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('normalizes column responses into jobs by id plus ordered column ids', async () => {
    const store = useJobsStore()
    const load = vi.fn().mockResolvedValue({
      success: true,
      jobs: [buildKanbanJob({ id: 'job-1' }), buildKanbanJob({ id: 'job-2' })],
      total: 2,
      filtered_count: 2,
      has_more: false,
    })

    await store.loadKanbanColumnWithCache('in_progress', load)

    expect(load).toHaveBeenCalledOnce()
    expect(store.kanbanColumnCache.in_progress).toMatchObject({
      jobIds: ['job-1', 'job-2'],
      total: 2,
      filtered_count: 2,
      has_more: false,
    })
    expect('jobs' in store.kanbanColumnCache.in_progress).toBe(false)
    expect(store.getKanbanColumnJobs('in_progress')?.map((job) => job.id)).toEqual([
      'job-1',
      'job-2',
    ])
  })

  it('resolves columns through the current job entity cache', async () => {
    const store = useJobsStore()

    await store.loadKanbanColumnWithCache('in_progress', async () => ({
      success: true,
      jobs: [buildKanbanJob({ id: 'job-1', name: 'Original' })],
      total: 1,
      filtered_count: 1,
      has_more: false,
    }))

    store.setKanbanJob(buildKanbanJob({ id: 'job-1', name: 'Updated' }))

    expect(store.getKanbanColumnJobs('in_progress')?.[0]?.name).toBe('Updated')
  })

  it('moves cached kanban job ids above or below a visible anchor', async () => {
    const store = useJobsStore()

    await store.loadKanbanColumnWithCache('in_progress', async () => ({
      success: true,
      jobs: [
        buildKanbanJob({ id: 'job-1' }),
        buildKanbanJob({ id: 'job-2' }),
        buildKanbanJob({ id: 'job-3' }),
      ],
      total: 3,
      filtered_count: 3,
      has_more: false,
    }))

    store.moveKanbanJobInColumnCache('job-3', 'in_progress', 'in_progress', 'job-1', 'below')

    expect(store.kanbanColumnCache.in_progress.jobIds).toEqual(['job-1', 'job-3', 'job-2'])

    store.moveKanbanJobInColumnCache('job-3', 'in_progress', 'in_progress', 'job-1', 'above')

    expect(store.kanbanColumnCache.in_progress.jobIds).toEqual(['job-3', 'job-1', 'job-2'])
  })

  it('invalidates a cached target column when the supplied anchor is not cached', async () => {
    const store = useJobsStore()

    await store.loadKanbanColumnWithCache('in_progress', async () => ({
      success: true,
      jobs: [buildKanbanJob({ id: 'job-1' }), buildKanbanJob({ id: 'job-2' })],
      total: 2,
      filtered_count: 2,
      has_more: false,
    }))

    store.moveKanbanJobInColumnCache('job-1', 'in_progress', 'in_progress', 'job-missing', 'below')

    expect(store.kanbanColumnCache.in_progress).toBeUndefined()
  })
})
