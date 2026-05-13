import { ref } from 'vue'

type CacheOptions<K, V> = {
  onInvalidate?: () => void
  getCached: (key: K) => V | null
  hasCached: (key: K) => boolean
  onResolved: (key: K, value: V) => void
}

type LoadOptions = {
  force?: boolean
}

export function createDatasetCache<K, V>(options: CacheOptions<K, V>) {
  const generation = ref(0)
  const inFlight = new Map<K, Promise<V>>()

  function invalidate(): void {
    generation.value += 1
    inFlight.clear()
    options.onInvalidate?.()
  }

  async function getOrLoad(
    key: K,
    load: () => Promise<V>,
    loadOptions: LoadOptions = {},
  ): Promise<V> {
    const force = loadOptions.force ?? false
    if (!force && options.hasCached(key)) {
      const cached = options.getCached(key)
      if (cached !== null) return cached
    }

    const existing = inFlight.get(key)
    if (existing && !force) return existing

    const startGeneration = generation.value
    const request = load()
      .then((value) => {
        if (startGeneration === generation.value) {
          options.onResolved(key, value)
          return value
        }
        return options.getCached(key) ?? value
      })
      .finally(() => {
        if (inFlight.get(key) === request) {
          inFlight.delete(key)
        }
      })

    inFlight.set(key, request)
    return request
  }

  return {
    generation,
    getOrLoad,
    invalidate,
  }
}
