import { describe, expect, it } from 'vitest'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import {
  buildPurchaseOrderCreateRequest,
  buildPurchaseOrderLineUpdate,
  buildPurchaseOrderSummaryUpdate,
  type EditablePurchaseOrderLine,
} from '../purchase-order'

const LINE_ID = '11111111-1111-4111-8111-111111111111'
const JOB_ID = '22222222-2222-4222-8222-222222222222'
type PurchaseOrderDetail = z.infer<typeof schemas.PurchaseOrderDetail>

function purchaseOrder(overrides: Partial<PurchaseOrderDetail> = {}): PurchaseOrderDetail {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    po_number: 'PO-1234',
    supplier: 'Example Supplier',
    supplier_id: '44444444-4444-4444-8444-444444444444',
    supplier_has_xero_id: true,
    pickup_address_id: null,
    pickup_address: null,
    reference: 'Workshop consumables',
    order_date: '2026-08-08',
    expected_delivery: null,
    status: 'draft',
    lines: [],
    created_by_id: null,
    created_by_name: 'Example User',
    ...overrides,
  }
}

function purchaseOrderLine(
  overrides: Partial<EditablePurchaseOrderLine> = {},
): EditablePurchaseOrderLine {
  return {
    id: LINE_ID,
    description: 'Free-description purchase',
    quantity: 2,
    dimensions: '100 x 50',
    unit_cost: 42.5,
    price_tbc: false,
    supplier_item_code: null,
    item_code: 'STOCK-1',
    received_quantity: 0,
    metal_type: 'mild_steel',
    alloy: 'A36',
    specifics: 'Laser cut',
    location: 'Rack 4',
    job_id: JOB_ID,
    job_number: 1234,
    company_name: 'Example Company',
    job_name: 'Example Job',
    times_used: 0,
    ...overrides,
  }
}

describe('buildPurchaseOrderLineUpdate', () => {
  it('sends every unset nullable text field as null for a draft line', () => {
    // Replacing absent values with empty strings caused the PO update to hit
    // database constraints and return 409 when a TBC price was confirmed.
    const result = buildPurchaseOrderLineUpdate(
      purchaseOrderLine({
        item_code: null,
        metal_type: undefined,
        alloy: '',
        specifics: '   ',
        location: null,
        dimensions: undefined,
      }),
      false,
    )

    expect(result).toMatchObject({
      item_code: null,
      metal_type: null,
      alloy: null,
      specifics: null,
      location: null,
      dimensions: null,
    })
    expect(schemas.PurchaseOrderLineUpdateRequest.parse(result)).toEqual(result)
  })

  it('keeps submitted purchase-order updates limited to identity and job assignment', () => {
    // Expanding submitted updates would let a refactor bypass the UI lock on
    // supplier-submitted line details.
    const result = buildPurchaseOrderLineUpdate(purchaseOrderLine(), true)

    expect(result).toEqual({
      id: LINE_ID,
      job_id: JOB_ID,
    })
  })

  it('rejects non-text values exposed by a generated enum union', () => {
    // The generated metal-type union is unknown at the client boundary, so a
    // malformed response must fail before it can become an update payload.
    expect(() =>
      buildPurchaseOrderLineUpdate(purchaseOrderLine({ metal_type: 123 }), false),
    ).toThrowError('Purchase-order text values must be strings or null')
  })
})

describe('purchase order reference payloads', () => {
  it('creates a purchase order with a null reference when the field is left blank', () => {
    // A blank reference must remain optional; sending an empty string violates
    // the API's single NULL representation for an unset nullable field.
    const result = buildPurchaseOrderCreateRequest(purchaseOrder({ reference: '   ' }))

    expect(result.reference).toBeNull()
    expect(schemas.PurchaseOrderCreateRequest.parse(result)).toEqual(result)
  })

  it('clears an existing purchase order reference with null', () => {
    // Edit autosave uses the same nullable contract as creation so clearing a
    // reference cannot regress to an empty-string PATCH.
    const result = buildPurchaseOrderSummaryUpdate(purchaseOrder({ reference: '' }), true)

    expect(result.reference).toBeNull()
    expect(schemas.PatchedPurchaseOrderUpdateRequest.parse(result)).toEqual(result)
  })
})
