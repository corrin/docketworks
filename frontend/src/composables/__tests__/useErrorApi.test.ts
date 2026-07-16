import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the generated company so we can assert exactly which query params each
// branch forwards to the backend.
const {
  xeroListMock,
  xeroGroupedMock,
  jobAdminListMock,
  jobGroupedMock,
  appListMock,
  appGroupedMock,
} = vi.hoisted(() => ({
  xeroListMock: vi.fn(),
  xeroGroupedMock: vi.fn(),
  jobAdminListMock: vi.fn(),
  jobGroupedMock: vi.fn(),
  appListMock: vi.fn(),
  appGroupedMock: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    xero_errors_list: xeroListMock,
    xero_errors_grouped_retrieve: xeroGroupedMock,
    job_rest_jobs_delta_rejections_admin_list: jobAdminListMock,
    job_jobs_delta_rejections_grouped_retrieve: jobGroupedMock,
    rest_app_errors_retrieve: appListMock,
    app_errors_grouped_retrieve: appGroupedMock,
  },
}))

import { useErrorApi } from '../useErrorApi'

const emptyList = { count: 0, next: null, previous: null, results: [] }

describe('useErrorApi xero/job filter forwarding', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    xeroListMock.mockResolvedValue(emptyList)
    xeroGroupedMock.mockResolvedValue(emptyList)
    jobAdminListMock.mockResolvedValue(emptyList)
    jobGroupedMock.mockResolvedValue(emptyList)
  })

  it('forwards app + resolved to the xero individual list endpoint', async () => {
    const { fetchErrors } = useErrorApi()
    await fetchErrors('xero', 1, { app: 'workflow', resolved: true })

    expect(xeroListMock).toHaveBeenCalledTimes(1)
    const queries = xeroListMock.mock.calls[0][0].queries
    expect(queries.app).toBe('workflow')
    expect(queries.resolved).toBe(true)
    // page 1 is the default and is not forwarded
    expect(queries.page).toBeUndefined()
  })

  it('forwards page + filters to the xero individual list endpoint when paginating', async () => {
    const { fetchErrors } = useErrorApi()
    await fetchErrors('xero', 3, { severity: 40 })

    const queries = xeroListMock.mock.calls[0][0].queries
    expect(queries.page).toBe(3)
    expect(queries.severity).toBe(40)
  })

  it('forwards app + resolved to the xero grouped endpoint', async () => {
    const { fetchGroupedErrors } = useErrorApi()
    await fetchGroupedErrors('xero', 1, { app: 'xero', resolved: false })

    expect(xeroGroupedMock).toHaveBeenCalledTimes(1)
    const queries = xeroGroupedMock.mock.calls[0][0].queries
    expect(queries.app).toBe('xero')
    expect(queries.resolved).toBe(false)
    expect(queries.limit).toBe(20)
    expect(queries.offset).toBe(0)
  })

  it('forwards resolved to the job individual list endpoint', async () => {
    const { fetchErrors } = useErrorApi()
    await fetchErrors('job', 1, { resolved: true })

    expect(jobAdminListMock).toHaveBeenCalledTimes(1)
    const queries = jobAdminListMock.mock.calls[0][0].queries
    expect(queries.resolved).toBe(true)
  })
})
