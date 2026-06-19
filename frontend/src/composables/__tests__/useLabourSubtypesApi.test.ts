import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useLabourSubtypesApi } from '../useLabourSubtypesApi'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    job_labour_subtypes_manage_list: vi.fn(),
    job_labour_subtypes_manage_create: vi.fn(),
    job_labour_subtypes_manage_retrieve: vi.fn(),
    job_labour_subtypes_manage_partial_update: vi.fn(),
  },
}))

const listMock = api.job_labour_subtypes_manage_list as ReturnType<typeof vi.fn>

describe('useLabourSubtypesApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('propagates list failures instead of converting them to an empty dataset', async () => {
    const failure = new Error('server unavailable')
    listMock.mockRejectedValue(failure)
    const { listLabourSubtypes, error } = useLabourSubtypesApi()

    await expect(listLabourSubtypes()).rejects.toThrow('server unavailable')
    expect(error.value).toBe('server unavailable')
  })
})
