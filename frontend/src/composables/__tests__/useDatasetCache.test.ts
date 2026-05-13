import { describe, expect, it, vi } from 'vitest'
import { createDatasetCache } from '../useDatasetCache'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('createDatasetCache', () => {
  it('returns cached data without calling the loader', async () => {
    const values = new Map([['all', ['cached']]])
    const onResolved = vi.fn()
    const cache = createDatasetCache<string, string[]>({
      getCached: (key) => values.get(key) ?? null,
      hasCached: (key) => values.has(key),
      onResolved,
    })

    const result = await cache.getOrLoad('all', vi.fn())

    expect(result).toEqual(['cached'])
    expect(onResolved).not.toHaveBeenCalled()
  })

  it('reuses in-flight loads for the same key', async () => {
    const values = new Map<string, string[]>()
    const pending = deferred<string[]>()
    const load = vi.fn(() => pending.promise)
    const cache = createDatasetCache<string, string[]>({
      getCached: (key) => values.get(key) ?? null,
      hasCached: (key) => values.has(key),
      onResolved: (key, value) => values.set(key, value),
    })

    const first = cache.getOrLoad('all', load)
    const second = cache.getOrLoad('all', load)
    pending.resolve(['loaded'])

    await expect(first).resolves.toEqual(['loaded'])
    await expect(second).resolves.toEqual(['loaded'])
    expect(load).toHaveBeenCalledOnce()
  })

  it('does not commit stale in-flight data after invalidation', async () => {
    const values = new Map<string, string[]>()
    const pending = deferred<string[]>()
    const onResolved = vi.fn((key: string, value: string[]) => values.set(key, value))
    const onInvalidate = vi.fn(() => values.clear())
    const cache = createDatasetCache<string, string[]>({
      getCached: (key) => values.get(key) ?? null,
      hasCached: (key) => values.has(key),
      onResolved,
      onInvalidate,
    })

    const result = cache.getOrLoad('all', () => pending.promise)
    cache.invalidate()
    pending.resolve(['stale'])

    await expect(result).resolves.toEqual(['stale'])
    expect(onInvalidate).toHaveBeenCalledOnce()
    expect(onResolved).not.toHaveBeenCalled()
    expect(values.has('all')).toBe(false)
  })
})
