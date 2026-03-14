import { ref, computed } from 'vue'
import { z } from 'zod'
import { schemas } from '@/api/generated/api'
import { debugLog } from '@/utils/debug'
import type { JobCacheEntry } from '@/constants/job-cache'

type JobDetailResponse = z.infer<typeof schemas.JobDetailResponse>

export function useJobCache() {
  const cache = ref<Map<string, JobCacheEntry>>(new Map())
  const currentVersion = ref(1)

  const DEFAULT_TTL = 5 * 60 * 1000

  const isCacheValid = (entry: JobCacheEntry, ttl: number = DEFAULT_TTL): boolean => {
    const now = new Date().getTime()
    const entryTime = entry.timestamp.getTime()
    const isWithinTTL = now - entryTime < ttl
    const isCurrentVersion = entry.version === currentVersion.value

    return isWithinTTL && isCurrentVersion
  }

  const getCachedJob = (jobId: string, ttl?: number): JobDetailResponse | null => {
    const entry = cache.value.get(jobId)

    if (!entry) {
      debugLog(`Cache miss for job ${jobId}`)
      return null
    }

    if (!isCacheValid(entry, ttl)) {
      debugLog(`Cache expired for job ${jobId}`)
      cache.value.delete(jobId)
      return null
    }

    debugLog(`Cache hit for job ${jobId}`)
    return entry.data
  }

  const setCachedJob = (jobId: string, jobData: JobDetailResponse): void => {
    const entry: JobCacheEntry = {
      data: { ...jobData },
      timestamp: new Date(),
      version: currentVersion.value,
    }

    cache.value.set(jobId, entry)
    debugLog(`Job ${jobId} cached`)
  }

  const removeCachedJob = (jobId: string): void => {
    if (cache.value.delete(jobId)) {
      debugLog(`Job ${jobId} removed from cache`)
    }
  }

  const invalidateAll = (): void => {
    currentVersion.value++
    debugLog(`Cache invalidated - new version: ${currentVersion.value}`)
  }

  const clearCache = (): void => {
    cache.value.clear()
    debugLog('Cache cleared')
  }

  const updateCachedJob = (jobId: string, updates: Partial<JobDetailResponse>): void => {
    const entry = cache.value.get(jobId)

    if (entry && isCacheValid(entry)) {
      const updatedData = { ...entry.data, ...updates }
      setCachedJob(jobId, updatedData)
      debugLog(`Job ${jobId} updated in cache`)
    }
  }

  const isCached = (jobId: string, ttl?: number): boolean => {
    const entry = cache.value.get(jobId)
    return entry ? isCacheValid(entry, ttl) : false
  }

  const cacheSize = computed(() => cache.value.size)

  const cacheStats = computed(() => {
    let validEntries = 0
    let expiredEntries = 0

    cache.value.forEach((entry) => {
      if (isCacheValid(entry)) {
        validEntries++
      } else {
        expiredEntries++
      }
    })

    return {
      total: cache.value.size,
      valid: validEntries,
      expired: expiredEntries,
    }
  })

  const withCache = async <T extends JobDetailResponse>(
    jobId: string,
    loadFunction: () => Promise<T>,
    ttl?: number,
  ): Promise<T> => {
    const cached = getCachedJob(jobId, ttl)
    if (cached) {
      return cached as T
    }

    debugLog(`Loading job ${jobId} from API...`)
    const freshData = await loadFunction()

    setCachedJob(jobId, freshData)

    return freshData
  }

  return {
    getCachedJob,
    setCachedJob,
    removeCachedJob,
    updateCachedJob,
    isCached,
    invalidateAll,
    clearCache,
    withCache,

    cacheSize,
    cacheStats,
    currentVersion: computed(() => currentVersion.value),
  }
}
