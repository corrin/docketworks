import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import WeeklyTimesheetView from '../WeeklyTimesheetView.vue'

const { mockRoute, mockRouter, fetchAllPayRunsMock, refreshPayRunsMock, fetchWeeklyOverviewMock } =
  vi.hoisted(() => ({
    mockRoute: {
      query: {},
    },
    mockRouter: {
      push: vi.fn(),
      replace: vi.fn(),
    },
    fetchAllPayRunsMock: vi.fn(),
    refreshPayRunsMock: vi.fn(),
    fetchWeeklyOverviewMock: vi.fn(),
  }))

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => mockRoute,
    useRouter: () => mockRouter,
  }
})

vi.mock('@/services/payroll.service', () => ({
  createPayRun: vi.fn(),
  postStaffWeek: vi.fn(),
  fetchAllPayRuns: fetchAllPayRunsMock,
  refreshPayRuns: refreshPayRunsMock,
}))

vi.mock('@/services/weekly-timesheet.service', () => ({
  fetchWeeklyOverview: fetchWeeklyOverviewMock,
  formatHours: (value: number) => String(value),
}))

vi.mock('@/stores/timesheet', () => ({
  useTimesheetStore: () => ({
    weekendEnabled: false,
  }),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('@/api/generated/api', () => ({
  schemas: {},
  endpoints: [],
}))

vi.mock('@/api/client', () => ({
  api: {},
  getApi: () => ({}),
}))

describe('WeeklyTimesheetView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRoute.query = {}
    fetchAllPayRunsMock.mockResolvedValue({
      pay_runs: [
        {
          id: '1',
          xero_id: 'xero-1',
          period_start_date: '2026-05-05',
          period_end_date: '2026-05-11',
          payment_date: '2026-05-13',
          pay_run_status: 'Draft',
          xero_url: 'https://example.test/payrun/1',
        },
      ],
    })
    refreshPayRunsMock.mockResolvedValue({
      synced: true,
      fetched: 1,
      created: 0,
      updated: 1,
    })
    fetchWeeklyOverviewMock.mockResolvedValue({
      start_date: '2026-05-05',
      end_date: '2026-05-11',
      week_days: ['2026-05-05', '2026-05-06', '2026-05-07', '2026-05-08', '2026-05-09'],
      staff_data: [],
    })
  })

  it('does not refresh pay runs from Xero on initial mount without a week query', async () => {
    mount(WeeklyTimesheetView, {
      global: {
        stubs: {
          AppLayout: { template: '<div><slot /></div>' },
          Button: { template: '<button><slot /></button>' },
          Label: { template: '<label><slot /></label>' },
          PayrollStaffRow: { template: '<div />' },
          WeeklyMetricsModal: { template: '<div />' },
          WeekPickerModal: { template: '<div />' },
          PayrollControlSection: { template: '<div />' },
        },
      },
    })

    await flushPromises()

    expect(fetchAllPayRunsMock).toHaveBeenCalledOnce()
    expect(refreshPayRunsMock).not.toHaveBeenCalled()
    expect(mockRouter.replace).toHaveBeenCalledWith({
      query: { week: '2026-05-04' },
    })
  })
})
