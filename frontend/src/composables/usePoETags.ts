/**
 * Composable for managing ETags for purchase order optimistic concurrency control
 *
 * Provides reactive storage and retrieval of ETags per purchase order ID.
 * ETags are stored in memory and automatically cleared when POs are no longer relevant.
 */

import { ref } from 'vue'
import { debugLog } from '@/utils/debug'

const etagByPo = ref(new Map<string, string>())

/**
 * Composable for managing ETags for purchase order endpoints
 *
 * @returns Object with ETag management functions
 */
export function usePoETags() {
  /**
   * Get the ETag for a specific purchase order
   * @param poId - The purchase order ID to get ETag for
   * @returns The ETag string or null if not found
   */
  const getETag = (poId: string): string | null => {
    return etagByPo.value.get(poId) || null
  }

  /**
   * Set the ETag for a specific purchase order
   * @param poId - The purchase order ID to set ETag for
   * @param etag - The ETag string to store
   */
  const setETag = (poId: string, etag: string): void => {
    if (etag && typeof etag === 'string') {
      etagByPo.value.set(poId, etag)
      debugLog('PO ETag stored:', { poId, etag })
    }
  }

  /**
   * Clear the ETag for a specific purchase order
   * @param poId - The purchase order ID to clear ETag for
   */
  const clearETag = (poId: string): void => {
    const hadETag = etagByPo.value.has(poId)
    etagByPo.value.delete(poId)
    if (hadETag) {
      debugLog('PO ETag cleared:', { poId })
    }
  }

  /**
   * Clear all stored PO ETags
   * Useful for logout or memory cleanup
   */
  const clearAllETags = (): void => {
    const count = etagByPo.value.size
    etagByPo.value.clear()
    if (count > 0) {
      debugLog('All PO ETags cleared:', { count })
    }
  }

  /**
   * Check if an ETag exists for a purchase order
   * @param poId - The purchase order ID to check
   * @returns True if ETag exists, false otherwise
   */
  const hasETag = (poId: string): boolean => {
    return etagByPo.value.has(poId)
  }

  /**
   * Get all stored purchase order IDs with ETags
   * @returns Array of purchase order IDs that have ETags
   */
  const getPoIdsWithETags = (): string[] => {
    return Array.from(etagByPo.value.keys())
  }

  /**
   * Get the current count of stored PO ETags
   * @returns Number of purchase orders with stored ETags
   */
  const getETagCount = (): number => {
    return etagByPo.value.size
  }

  return {
    // Reactive getters
    getETag,
    hasETag,
    getPoIdsWithETags,
    getETagCount,

    // Actions
    setETag,
    clearETag,
    clearAllETags,
  }
}
