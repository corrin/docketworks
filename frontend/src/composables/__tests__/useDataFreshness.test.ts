import { beforeEach, describe, expect, it, vi } from 'vitest'

const { retrieveDataVersions } = vi.hoisted(() => ({
  retrieveDataVersions: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    data_versions_retrieve: retrieveDataVersions,
  },
}))

import { dataFreshness } from '@/composables/useDataFreshness'

describe('useDataFreshness', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    dataFreshness._resetForTesting()
  })

  it('passes the previous and current opaque versions to stale subscribers', async () => {
    const onStale = vi.fn()
    dataFreshness.subscribe('kanban', onStale)
    retrieveDataVersions
      .mockResolvedValueOnce({ kanban: 'version-1' })
      .mockResolvedValueOnce({ kanban: 'version-2' })

    await dataFreshness.checkFreshness()
    await dataFreshness.checkFreshness()

    expect(onStale).toHaveBeenCalledWith('version-1', 'version-2')
  })

  it('retries a version change when its subscriber fails', async () => {
    const failure = new Error('incremental refresh failed')
    const onStale = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce(undefined)
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    dataFreshness.subscribe('kanban', onStale)
    retrieveDataVersions
      .mockResolvedValueOnce({ kanban: 'version-1' })
      .mockResolvedValue({ kanban: 'version-2' })

    await dataFreshness.checkFreshness()
    await dataFreshness.checkFreshness()
    await dataFreshness.checkFreshness()

    expect(onStale).toHaveBeenCalledTimes(2)
    expect(consoleError).toHaveBeenCalled()
    consoleError.mockRestore()
  })
})
