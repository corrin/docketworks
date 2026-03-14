/**
 * Composable for managing ETags for optimistic concurrency control
 *
 * Provides reactive storage and retrieval of ETags per job ID.
 * ETags are stored in memory and automatically cleared when jobs are no longer relevant.
 */

import { ref } from 'vue'
import { debugLog } from '@/utils/debug'

const etagByJob = ref(new Map<string, string>())

/**
 * Composable for managing ETags for job endpoints
 *
 * @returns Object with ETag management functions
 */
export function useJobETags() {
  /**
   * Get the ETag for a specific job
   * @param jobId - The job ID to get ETag for
   * @returns The ETag string or null if not found
   */
  const getETag = (jobId: string): string | null => {
    return etagByJob.value.get(jobId) || null
  }

  /**
   * Set the ETag for a specific job
   * @param jobId - The job ID to set ETag for
   * @param etag - The ETag string to store
   */
  const setETag = (jobId: string, etag: string): void => {
    if (etag && typeof etag === 'string') {
      etagByJob.value.set(jobId, etag)
      debugLog('ETag stored:', { jobId, etag })
    }
  }

  /**
   * Clear the ETag for a specific job
   * @param jobId - The job ID to clear ETag for
   */
  const clearETag = (jobId: string): void => {
    const hadETag = etagByJob.value.has(jobId)
    etagByJob.value.delete(jobId)
    if (hadETag) {
      debugLog('ETag cleared:', { jobId })
    }
  }

  /**
   * Clear all stored ETags
   * Useful for logout or memory cleanup
   */
  const clearAllETags = (): void => {
    const count = etagByJob.value.size
    etagByJob.value.clear()
    if (count > 0) {
      debugLog('All ETags cleared:', { count })
    }
  }

  /**
   * Check if an ETag exists for a job
   * @param jobId - The job ID to check
   * @returns True if ETag exists, false otherwise
   */
  const hasETag = (jobId: string): boolean => {
    return etagByJob.value.has(jobId)
  }

  /**
   * Get all stored job IDs with ETags
   * @returns Array of job IDs that have ETags
   */
  const getJobIdsWithETags = (): string[] => {
    return Array.from(etagByJob.value.keys())
  }

  /**
   * Get the current count of stored ETags
   * @returns Number of jobs with stored ETags
   */
  const getETagCount = (): number => {
    return etagByJob.value.size
  }

  return {
    // Reactive getters
    getETag,
    hasETag,
    getJobIdsWithETags,
    getETagCount,

    // Actions
    setETag,
    clearETag,
    clearAllETags,
  }
}

// Debug logging is handled by the imported debugLog function
