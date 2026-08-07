import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type PurchaseOrderLine = z.infer<typeof schemas.PurchaseOrderLine>
type PurchaseOrderLineUpdateRequest = z.infer<typeof schemas.PurchaseOrderLineUpdateRequest>
type PurchaseOrderDetail = z.infer<typeof schemas.PurchaseOrderDetail>
type PurchaseOrderCreateRequest = z.infer<typeof schemas.PurchaseOrderCreateRequest>
type PurchaseOrderUpdateRequest = z.infer<typeof schemas.PatchedPurchaseOrderUpdateRequest>

export type EditablePurchaseOrderLine = PurchaseOrderLine

function nullIfBlank(value: unknown): string | null {
  if (value == null) {
    return null
  }

  if (typeof value !== 'string') {
    throw new TypeError('Purchase-order text values must be strings or null')
  }

  if (value.trim() === '') {
    return null
  }

  return value
}

export function buildPurchaseOrderCreateRequest(
  purchaseOrder: PurchaseOrderDetail,
): PurchaseOrderCreateRequest {
  return {
    supplier_id: purchaseOrder.supplier_id || null,
    reference: nullIfBlank(purchaseOrder.reference),
    order_date: purchaseOrder.order_date || null,
    expected_delivery: purchaseOrder.expected_delivery || null,
    lines: [],
  }
}

export function buildPurchaseOrderSummaryUpdate(
  purchaseOrder: PurchaseOrderDetail,
  includeSupplier: boolean,
): PurchaseOrderUpdateRequest {
  const request: PurchaseOrderUpdateRequest = {
    reference: nullIfBlank(purchaseOrder.reference),
    expected_delivery: purchaseOrder.expected_delivery,
    status: purchaseOrder.status,
  }

  if (includeSupplier) {
    if (purchaseOrder.supplier_id) {
      request.supplier_id = purchaseOrder.supplier_id
    }
    request.pickup_address_id = purchaseOrder.pickup_address_id || null
  }

  return request
}

export function buildPurchaseOrderLineUpdate(
  line: EditablePurchaseOrderLine,
  isSubmitted: boolean,
): PurchaseOrderLineUpdateRequest {
  const id = nullIfBlank(line.id)
  const jobId = nullIfBlank(line.job_id)

  if (isSubmitted) {
    return {
      id,
      job_id: jobId,
    }
  }

  return {
    id,
    job_id: jobId,
    description: line.description,
    quantity: line.quantity,
    unit_cost: line.unit_cost,
    price_tbc: line.price_tbc,
    item_code: nullIfBlank(line.item_code),
    metal_type: nullIfBlank(line.metal_type),
    alloy: nullIfBlank(line.alloy),
    specifics: nullIfBlank(line.specifics),
    location: nullIfBlank(line.location),
    dimensions: nullIfBlank(line.dimensions),
  }
}
