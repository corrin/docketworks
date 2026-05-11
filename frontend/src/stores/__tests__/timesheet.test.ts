import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTimesheetStore } from '@/stores/timesheet'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    timesheets_staff_retrieve: vi.fn(),
    timesheets_jobs_retrieve: vi.fn(),
    workflow_xero_pay_items_list: vi.fn(),
    company_defaults_retrieve: vi.fn(),
  },
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

describe('timesheet store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(api.timesheets_staff_retrieve).mockResolvedValue({
      staff: [],
      total_count: 0,
    })
  })

  it('loads the staff list for the selected timesheet date', async () => {
    const store = useTimesheetStore()

    await store.loadStaff('2025-05-05')

    expect(api.timesheets_staff_retrieve).toHaveBeenCalledWith({
      queries: { date: '2025-05-05' },
    })
  })
})
