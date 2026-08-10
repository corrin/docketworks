import type { PurchaseOrderLineUpdateRequest } from '@/api'

/**
 * A not-yet-persisted PO line. Wire decimals stay strings end to end;
 * `job_number` is display-only so JobSelect can render a pick before the
 * detail refetch supplies the server's line.
 */
export interface PoLineDraft {
  description: string
  quantity: string
  unit_cost: string | null
  item_code: string | null
  metal_type: string | null
  alloy: string | null
  specifics: string | null
  location: string | null
  job_id: string | null
  job_number: number | null
}

export function emptyPoLineDraft(): PoLineDraft {
  return {
    description: '',
    quantity: '1',
    unit_cost: null,
    item_code: null,
    metal_type: null,
    alloy: null,
    specifics: null,
    location: null,
    job_id: null,
    job_number: null,
  }
}

export function poLineDraftIsEmpty(draft: PoLineDraft): boolean {
  return (
    draft.description.trim() === '' &&
    draft.quantity === '1' &&
    draft.unit_cost === null &&
    draft.item_code === null &&
    draft.job_id === null
  )
}

/** Enough content to PATCH: the backend accepts a description-only line. */
export function poLineDraftIsReady(draft: PoLineDraft): boolean {
  return draft.description.trim() !== ''
}

/**
 * The upsert entry for a draft (no `id`, so the backend creates the line).
 * Optional fields are sent only when set: the endpoint writes exactly the
 * keys present, and the NullableText columns 422 on empty strings.
 */
export function draftCreateBody(draft: PoLineDraft): PurchaseOrderLineUpdateRequest {
  const body: PurchaseOrderLineUpdateRequest = {
    description: draft.description,
    quantity: draft.quantity,
  }
  if (draft.unit_cost !== null) body.unit_cost = draft.unit_cost
  if (draft.item_code !== null) body.item_code = draft.item_code
  if (draft.metal_type !== null) body.metal_type = draft.metal_type
  if (draft.alloy !== null) body.alloy = draft.alloy
  if (draft.specifics !== null) body.specifics = draft.specifics
  if (draft.location !== null) body.location = draft.location
  if (draft.job_id !== null) body.job_id = draft.job_id
  return body
}
