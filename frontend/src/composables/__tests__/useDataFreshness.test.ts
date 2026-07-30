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

  it('does not let a stale unsubscribe remove a newer subscriber bucket', async () => {
    const firstSubscriber = vi.fn()
    const unsubscribeFirst = dataFreshness.subscribe('kanban', firstSubscriber)
    retrieveDataVersions.mockResolvedValueOnce({ kanban: 'version-1' })
    await dataFreshness.checkFreshness()

    unsubscribeFirst()
    const newerSubscriber = vi.fn()
    dataFreshness.subscribe('kanban', newerSubscriber)
    unsubscribeFirst()
    retrieveDataVersions.mockResolvedValueOnce({ kanban: 'version-2' })

    await dataFreshness.checkFreshness()

    expect(newerSubscriber).toHaveBeenCalledWith('version-1', 'version-2')
  })

  it('runs every callback, surfaces the original failure, and retries only its dataset', async () => {
    const failure = new Error('incremental refresh failed')
    const failingKanbanSubscriber = vi
      .fn()
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce(undefined)
    const successfulKanbanSubscriber = vi.fn()
    const stockSubscriber = vi.fn()
    dataFreshness.subscribe('kanban', failingKanbanSubscriber)
    dataFreshness.subscribe('kanban', successfulKanbanSubscriber)
    dataFreshness.subscribe('stock', stockSubscriber)
    retrieveDataVersions
      .mockResolvedValueOnce({ kanban: 'kanban-1', stock: 'stock-1' })
      .mockResolvedValue({ kanban: 'kanban-2', stock: 'stock-2' })

    await dataFreshness.checkFreshness()
    await expect(dataFreshness.checkFreshness()).rejects.toBe(failure)
    await dataFreshness.checkFreshness()

    expect(failingKanbanSubscriber).toHaveBeenCalledTimes(2)
    expect(successfulKanbanSubscriber).toHaveBeenCalledTimes(2)
    expect(successfulKanbanSubscriber).toHaveBeenNthCalledWith(2, 'kanban-1', 'kanban-2')
    expect(stockSubscriber).toHaveBeenCalledOnce()
    expect(stockSubscriber).toHaveBeenCalledWith('stock-1', 'stock-2')
  })

  it('aggregates multiple callback failures after every callback runs', async () => {
    const firstFailure = new Error('first failure')
    const secondFailure = new Error('second failure')
    const firstSubscriber = vi.fn().mockRejectedValue(firstFailure)
    const secondSubscriber = vi.fn().mockRejectedValue(secondFailure)
    dataFreshness.subscribe('kanban', firstSubscriber)
    dataFreshness.subscribe('kanban', secondSubscriber)
    retrieveDataVersions
      .mockResolvedValueOnce({ kanban: 'version-1' })
      .mockResolvedValueOnce({ kanban: 'version-2' })

    await dataFreshness.checkFreshness()
    const result = dataFreshness.checkFreshness()

    await expect(result).rejects.toBeInstanceOf(AggregateError)
    await expect(result).rejects.toMatchObject({
      errors: [firstFailure, secondFailure],
    })
    expect(firstSubscriber).toHaveBeenCalledOnce()
    expect(secondSubscriber).toHaveBeenCalledOnce()
  })
})
