import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_ADVANCED_FILTERS } from '@/constants/advanced-filters'

const { advancedSearch } = vi.hoisted(() => ({
  advancedSearch: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_advanced_search_retrieve: advancedSearch,
  },
}))

import { jobService } from '@/services/job.service'

describe('jobService advanced search', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    advancedSearch.mockResolvedValue({ jobs: [] })
  })

  it('normalizes status arrays at the API boundary', async () => {
    await jobService.performAdvancedSearch({
      ...DEFAULT_ADVANCED_FILTERS,
      status: ['draft', 'approved'],
    })
    await jobService.performAdvancedSearch({
      ...DEFAULT_ADVANCED_FILTERS,
      status: [],
    })

    expect(advancedSearch).toHaveBeenNthCalledWith(1, {
      queries: expect.objectContaining({ status: 'draft,approved' }),
    })
    expect(advancedSearch).toHaveBeenNthCalledWith(2, {
      queries: expect.objectContaining({ status: '' }),
    })
  })
})
