import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import WeeklyTimesheetView from '../WeeklyTimesheetView.vue'
import { postStaffWeek } from '@/services/payroll.service'
import { toast } from 'vue-sonner'

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

vi.mock('@/composables/useXeroConnection', () => ({
  useXeroConnection: () => ({
    xeroConnected: { value: true },
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
          period_start_date: '2026-05-04',
          period_end_date: '2026-05-10',
          payment_date: '2026-05-13',
          pay_run_status: 'Draft',
          xero_url: 'https://example.test/payrun/1',
        },
      ],
      next_postable_week_start_date: '2026-05-04',
      next_postable_week_end_date: '2026-05-10',
    })
    refreshPayRunsMock.mockResolvedValue({
      synced: true,
      fetched: 1,
      created: 0,
      updated: 1,
    })
    fetchWeeklyOverviewMock.mockResolvedValue({
      start_date: '2026-05-05',
      end_date: '2026-05-09',
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

  it('lands on the backend postable week and enables Post to Xero there', async () => {
    const postingBlockedSpy = vi.fn()
    mount(WeeklyTimesheetView, {
      global: {
        stubs: {
          AppLayout: { template: '<div><slot /></div>' },
          Button: { template: '<button><slot /></button>' },
          Label: { template: '<label><slot /></label>' },
          PayrollStaffRow: { template: '<div />' },
          WeeklyMetricsModal: { template: '<div />' },
          WeekPickerModal: { template: '<div />' },
          PayrollControlSection: {
            props: ['postingBlocked', 'nextPostableWeekStart'],
            template: '<div :data-blocked="String(postingBlocked)" />',
            mounted() {
              postingBlockedSpy(this.postingBlocked, this.nextPostableWeekStart)
            },
          },
        },
      },
    })

    await flushPromises()

    expect(mockRouter.replace).toHaveBeenCalledWith({ query: { week: '2026-05-04' } })
    // Displayed week IS the postable week → posting is not blocked
    expect(postingBlockedSpy).toHaveBeenLastCalledWith(false, '2026-05-04')
  })

  it('disables Post to Xero on a non-postable week and offers "Go to that week"', async () => {
    mockRoute.query = { week: '2026-05-11' }
    fetchWeeklyOverviewMock.mockResolvedValue({
      start_date: '2026-05-11',
      end_date: '2026-05-15',
      week_days: ['2026-05-11', '2026-05-12', '2026-05-13', '2026-05-14', '2026-05-15'],
      staff_data: [],
    })

    const wrapper = mount(WeeklyTimesheetView, {
      global: {
        stubs: {
          AppLayout: { template: '<div><slot /></div>' },
          Button: { template: '<button><slot /></button>' },
          Label: { template: '<label><slot /></label>' },
          PayrollStaffRow: { template: '<div />' },
          WeeklyMetricsModal: { template: '<div />' },
          WeekPickerModal: { template: '<div />' },
          PayrollControlSection: {
            props: ['postingBlocked', 'postingBlockedReason', 'nextPostableWeekStart'],
            template:
              '<div><span data-test="blocked">{{ String(postingBlocked) }}</span>' +
              '<span data-test="reason">{{ postingBlockedReason }}</span>' +
              '<button data-test="go" @click="$emit(\'goToPostableWeek\')">Go to that week</button></div>',
          },
        },
      },
    })

    await flushPromises()

    expect(wrapper.get('[data-test="blocked"]').text()).toBe('true')
    expect(wrapper.get('[data-test="reason"]').text()).toContain('is next')

    await wrapper.get('[data-test="go"]').trigger('click')
    await flushPromises()

    expect(mockRouter.push).toHaveBeenCalledWith({ query: { week: '2026-05-04' } })
  })

  it('refreshes local pay runs after successful payroll post without a second pay-run create', async () => {
    mockRoute.query = { week: '2026-05-04' }
    fetchWeeklyOverviewMock.mockResolvedValue({
      start_date: '2026-05-04',
      end_date: '2026-05-08',
      week_days: ['2026-05-04', '2026-05-05', '2026-05-06', '2026-05-07', '2026-05-08'],
      staff_data: [
        {
          staff_id: 'staff-1',
          name: 'Pat Example',
          weekly_hours: [null, null, null, null, null],
          total_hours: 8,
          total_billable_hours: 8,
          weekly_cost: 1,
          weekly_base_cost: 1,
        },
      ],
    })
    vi.mocked(postStaffWeek).mockResolvedValue({
      event: 'done',
      successful: 1,
      failed: 0,
    })

    const wrapper = mount(WeeklyTimesheetView, {
      global: {
        stubs: {
          AppLayout: { template: '<div><slot /></div>' },
          Button: { template: '<button><slot /></button>' },
          Label: { template: '<label><slot /></label>' },
          PayrollStaffRow: { template: '<div />' },
          WeeklyMetricsModal: { template: '<div />' },
          WeekPickerModal: { template: '<div />' },
          PayrollControlSection: {
            template: '<button data-test="post" @click="$emit(\'postAllToXero\')">Post</button>',
          },
        },
      },
    })

    await flushPromises()
    await wrapper.get('[data-test="post"]').trigger('click')
    await flushPromises()

    expect(postStaffWeek).toHaveBeenCalledOnce()
    expect(fetchAllPayRunsMock).toHaveBeenCalledTimes(2)
    expect(toast.success).toHaveBeenCalledWith('All staff posted successfully', {
      description: '1 staff members posted to Xero.',
    })
  })
})
