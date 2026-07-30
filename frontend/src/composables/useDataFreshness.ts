import { api } from '@/api/client'

type StaleCallback = (previousVersion: string, currentVersion: string) => void | Promise<void>

const knownVersions = new Map<string, string>()
const subscribers = new Map<string, Set<StaleCallback>>()
let inFlight: Promise<void> | null = null

/**
 * Register a callback fired when `key`'s version changes from one observed
 * value to another. First observation is not a change; the store is
 * responsible for its own initial fetch. Returns an unsubscribe function.
 */
function subscribe(key: string, onStale: StaleCallback): () => void {
  let bucket = subscribers.get(key)
  if (!bucket) {
    bucket = new Set()
    subscribers.set(key, bucket)
  }
  bucket.add(onStale)
  return () => {
    bucket?.delete(onStale)
    if (bucket && bucket.size === 0 && subscribers.get(key) === bucket) {
      subscribers.delete(key)
    }
  }
}

/**
 * Pull current dataset versions from the backend, diff against last seen,
 * fire subscribers for any key whose version changed. Concurrent callers
 * share a single in-flight request — there is never a reason to issue
 * `data-versions/` twice in parallel.
 */
async function checkFreshness(): Promise<void> {
  if (inFlight) return inFlight
  inFlight = (async () => {
    try {
      const callbackErrors: unknown[] = []
      const fresh = (await api.data_versions_retrieve()) as Record<string, string>
      for (const [key, version] of Object.entries(fresh)) {
        const previous = knownVersions.get(key)
        if (previous === undefined) {
          knownVersions.set(key, version)
          continue
        }
        if (previous === version) continue
        const bucket = subscribers.get(key)
        if (!bucket) continue
        let callbacksSucceeded = true
        for (const cb of bucket) {
          try {
            await cb(previous, version)
          } catch (err) {
            callbacksSucceeded = false
            callbackErrors.push(err)
          }
        }
        if (callbacksSucceeded) {
          knownVersions.set(key, version)
        }
      }
      if (callbackErrors.length === 1) {
        throw callbackErrors[0]
      }
      if (callbackErrors.length > 1) {
        throw new AggregateError(callbackErrors, 'Multiple data freshness subscribers failed')
      }
    } finally {
      inFlight = null
    }
  })()
  return inFlight
}

/** Test-only: drop all subscribers and known versions. */
function _resetForTesting(): void {
  knownVersions.clear()
  subscribers.clear()
  inFlight = null
}

export const dataFreshness = {
  subscribe,
  checkFreshness,
  _resetForTesting,
}
