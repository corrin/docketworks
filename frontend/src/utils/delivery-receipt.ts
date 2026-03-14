/**
 * Delivery Receipt Utilities
 *
 * Frontend utilities for handling delivery receipt data transformation and UI types.
 * These are frontend responsibilities - data transformation and UI presentation.
 */

import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

// Generated API types
type DeliveryReceiptLine = z.infer<typeof schemas.DeliveryReceiptLineRequest>
type DeliveryReceiptRequest = z.infer<typeof schemas.DeliveryReceiptRequest>

// Use generated API types only
export type DeliveryAllocation = z.infer<typeof schemas.DeliveryReceiptAllocationRequest>
// SCheduled for deletion but kept for reference

/**
 * Transform frontend UI allocations data to backend API format
 */
export function transformDeliveryReceiptForAPI(
  purchaseOrderId: string,
  uiAllocations: Record<string, DeliveryAllocation[]>,
): DeliveryReceiptRequest {
  const apiAllocations: Record<string, DeliveryReceiptLine> = {}

  for (const [lineId, allocations] of Object.entries(uiAllocations)) {
    if (allocations.length > 0) {
      const total_received = allocations.reduce((sum, a) => {
        const q = typeof a.quantity === 'number' ? a.quantity : 0
        return sum + q
      }, 0)

      apiAllocations[lineId] = {
        total_received,
        allocations: allocations.map((allocation) => ({
          job_id: allocation.job_id,
          quantity: allocation.quantity,
          // NOTE: Generated schema only has job_id and quantity
          // Backend needs to expand DeliveryReceiptAllocation schema
          // to include unit_cost, retail_rate, notes fields
        })),
      }
    }
  }

  return {
    purchase_order_id: purchaseOrderId,
    allocations: apiAllocations,
  }
}

/**
 * Initialize empty allocations structure for UI
 */
export function initializeEmptyAllocations(
  lineIds: string[],
): Record<string, DeliveryAllocation[]> {
  const allocations: Record<string, DeliveryAllocation[]> = {}
  lineIds.forEach((lineId) => {
    allocations[lineId] = []
  })
  return allocations
}
