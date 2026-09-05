import type { JobForPurchasing, PurchaseOrderLineUpdateRequest } from '@/api'

// A PO line never books against a closed job (v1 rule).
const EXCLUDED_STATUSES = new Set(['rejected', 'archived', 'completed'])

/** The jobs a PO line may book against. Applied once where the query is read,
    not per row — the picker itself holds no eligibility rule. */
export function jobsBookableOnPoLine(
  jobs: readonly JobForPurchasing[],
): readonly JobForPurchasing[] {
  return jobs.filter((job) => !EXCLUDED_STATUSES.has(job.status.toLowerCase()))
}

/** The bound job as a PO line shows it. */
export function poLineJobLabel(jobNumber: number | null, jobName: string | null): string {
  if (jobNumber === null) return ''
  return jobName === null || jobName === '' ? String(jobNumber) : `${jobNumber} - ${jobName}`
}

/**
 * A not-yet-persisted PO line. Wire decimals stay strings end to end;
 * `job_number`/`job_name` are display-only so the job picker can render a pick
 * before the detail refetch supplies the server's line.
 */
export interface PoLineDraft {
  description: string
  quantity: string
  unit_cost: string | null
  price_tbc: boolean
  item_code: string | null
  metal_type: string | null
  alloy: string | null
  specifics: string | null
  location: string | null
  job_id: string | null
  job_number: number | null
  job_name: string | null
}

export function emptyPoLineDraft(): PoLineDraft {
  return {
    description: '',
    quantity: '1',
    unit_cost: null,
    price_tbc: false,
    item_code: null,
    metal_type: null,
    alloy: null,
    specifics: null,
    location: null,
    job_id: null,
    job_number: null,
    job_name: null,
  }
}

/**
 * The item picker's trigger label. item_code is nullable (v1 parity — some
 * stock carries none), so a bound line with no code must still show its
 * description rather than reading as unbound. 'Select Item' is reserved for
 * a genuinely empty line — the E2E repair loop counts buttons by that exact
 * name and must stop matching a row once it is bound.
 */
export function poLineItemLabel(itemCode: string | null, description: string): string {
  if (itemCode !== null) return itemCode
  return description.trim() !== '' ? description : 'Select Item'
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
  // Sent only when set, so an untouched draft does not assert "priced" against
  // a service whose default is already false.
  if (draft.price_tbc) body.price_tbc = true
  if (draft.item_code !== null) body.item_code = draft.item_code
  if (draft.metal_type !== null) body.metal_type = draft.metal_type
  if (draft.alloy !== null) body.alloy = draft.alloy
  if (draft.specifics !== null) body.specifics = draft.specifics
  if (draft.location !== null) body.location = draft.location
  if (draft.job_id !== null) body.job_id = draft.job_id
  return body
}

/**
 * The Jobs cell on the PO list: one number, two joined, or the first plus a
 * count.
 *
 * Opus: a PO covering many jobs is normal, so the cell states how many rather
 * than growing with them — the full set is on the row's title attribute and
 * the detail page. An em dash means the order is not booked to a job at all,
 * which is different from having none listed.
 */
export function poListJobsLabel(jobs: readonly { job_number: string }[]): string {
  if (jobs.length === 0) return '—'
  if (jobs.length === 1) return jobs[0]!.job_number
  if (jobs.length === 2) return `${jobs[0]!.job_number}, ${jobs[1]!.job_number}`
  return `${jobs[0]!.job_number} +${jobs.length - 1} others`
}
