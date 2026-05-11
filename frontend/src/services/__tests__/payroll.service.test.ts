import { describe, it, expect, vi, beforeEach } from 'vitest'
import { postStaffWeek, fetchAllPayRuns } from '../payroll.service'

const { createMock, payRunsRetrieveMock, eventSourceInstances, getApiBaseUrlMock } = vi.hoisted(
  () => {
    const instances: Array<{
      onmessage: ((event: MessageEvent) => void) | null
      onerror: (() => void) | null
      close: ReturnType<typeof vi.fn>
      url: string
    }> = []

    class MockEventSource {
      onmessage: ((event: MessageEvent) => void) | null = null
      onerror: (() => void) | null = null
      close = vi.fn()
      url: string

      constructor(url: string) {
        this.url = url
        instances.push(this)
      }
    }

    vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource)

    return {
      createMock: vi.fn(),
      payRunsRetrieveMock: vi.fn(),
      eventSourceInstances: instances,
      getApiBaseUrlMock: vi.fn(() => 'https://example.test'),
    }
  },
)

vi.mock('@/api/client', () => ({
  api: {
    timesheets_payroll_post_staff_week_create: createMock,
    timesheets_payroll_pay_runs_retrieve: payRunsRetrieveMock,
  },
}))

vi.mock('@/api/generated/api', () => ({
  schemas: {},
}))

vi.mock('@/plugins/axios', () => ({
  getApiBaseUrl: getApiBaseUrlMock,
}))

describe('postStaffWeek', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    eventSourceInstances.length = 0
  })

  it('accepts the start-job payload and resolves from SSE done event', async () => {
    createMock.mockResolvedValue({
      task_id: 'task-1',
      stream_url: '/api/timesheets/payroll/post-staff-week/stream/task-1/',
    })

    const promise = postStaffWeek(['staff-1'], '2026-05-04')
    await Promise.resolve()

    expect(createMock).toHaveBeenCalledWith({
      staff_ids: ['staff-1'],
      week_start_date: '2026-05-04',
    })
    expect(eventSourceInstances).toHaveLength(1)
    expect(eventSourceInstances[0].url).toBe(
      'https://example.test/api/timesheets/payroll/post-staff-week/stream/task-1/',
    )

    eventSourceInstances[0].onmessage?.({
      data: JSON.stringify({ event: 'done', successful: 1, failed: 0 }),
    } as MessageEvent)

    await expect(promise).resolves.toEqual({
      event: 'done',
      successful: 1,
      failed: 0,
    })
    expect(eventSourceInstances[0].close).toHaveBeenCalledOnce()
  })

  it('forwards top-level payroll error events before done', async () => {
    createMock.mockResolvedValue({
      task_id: 'task-2',
      stream_url: '/api/timesheets/payroll/post-staff-week/stream/task-2/',
    })
    const onStreamError = vi.fn()

    const promise = postStaffWeek(['staff-1'], '2026-05-04', { onStreamError })
    await Promise.resolve()

    eventSourceInstances[0].onmessage?.({
      data: JSON.stringify({
        event: 'error',
        message: 'The selected week is not a valid Xero pay period',
      }),
    } as MessageEvent)
    eventSourceInstances[0].onmessage?.({
      data: JSON.stringify({ event: 'done', successful: 0, failed: 1 }),
    } as MessageEvent)

    await expect(promise).resolves.toEqual({
      event: 'done',
      successful: 0,
      failed: 1,
    })
    expect(onStreamError).toHaveBeenCalledWith({
      event: 'error',
      message: 'The selected week is not a valid Xero pay period',
    })
  })
})

describe('fetchAllPayRuns', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns the pay runs alongside the backend-chosen postable week', async () => {
    payRunsRetrieveMock.mockResolvedValue({
      pay_runs: [
        {
          id: '1',
          xero_id: 'xero-1',
          period_start_date: '2026-05-04',
          period_end_date: '2026-05-10',
          payment_date: '2026-05-12',
          pay_run_status: 'Posted',
          xero_url: 'https://example.test/payrun/1',
        },
      ],
      next_postable_week_start_date: '2026-05-11',
      next_postable_week_end_date: '2026-05-17',
    })

    const result = await fetchAllPayRuns()

    expect(payRunsRetrieveMock).toHaveBeenCalledOnce()
    expect(result.pay_runs).toHaveLength(1)
    expect(result.next_postable_week_start_date).toBe('2026-05-11')
    expect(result.next_postable_week_end_date).toBe('2026-05-17')
  })

  it('passes through null postable-week fields for an unconfigured org', async () => {
    payRunsRetrieveMock.mockResolvedValue({
      pay_runs: [],
      next_postable_week_start_date: null,
      next_postable_week_end_date: null,
    })

    const result = await fetchAllPayRuns()

    expect(result.next_postable_week_start_date).toBeNull()
    expect(result.next_postable_week_end_date).toBeNull()
  })
})
