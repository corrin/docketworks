/**
 * ETag / If-Match interceptor logic for optimistic concurrency (ADR 0003), axios-free:
 * src/api/client.ts wires these onto the generated client's axios instance.
 *
 * - Responses from versioned Job/PO endpoints have their strong
 *   ETag / X-Resource-Version captured into the etag store.
 * - Mutating Job/PO requests get an If-Match header from the store.
 * - 412 (conflict) / 428 (missing If-Match) invalidate the resource's query via
 *   the registered invalidator, toast with a Retry action (retry-bus), and
 *   reject with ConcurrencyError.
 */
import { toast } from 'sonner'

import { etagKey, getEtag, setEtag } from './etag-store'
import { emitConcurrencyRetry, type ResourceKind } from './retry-bus'

export class ConcurrencyError extends Error {
  readonly kind: ResourceKind
  readonly resourceId: string

  constructor(message: string, kind: ResourceKind, resourceId: string) {
    super(message)
    this.name = 'ConcurrencyError'
    this.kind = kind
    this.resourceId = resourceId
  }
}

export function isConcurrencyError(error: unknown): error is ConcurrencyError {
  return error instanceof ConcurrencyError
}

// --- Strong-version header filtering ---

function strongHeaderValue(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }
  const normalized = value.trim()
  if (!normalized || /^W\//i.test(normalized)) {
    return null
  }
  return normalized
}

/** Headers with lowercased keys, as axios normalizes response headers. */
export function strongResourceVersion(headers: Record<string, unknown>): string | null {
  return (
    strongHeaderValue(headers['x-resource-version']) ?? strongHeaderValue(headers['etag']) ?? null
  )
}

// --- Resource rules ---

interface StatusMessages {
  toast: string
  error: string
}

interface ResourceRule {
  kind: ResourceKind
  /** Endpoints whose responses carry a capturable resource version. */
  isVersionedEndpoint: (url: string) => boolean
  /** Endpoints whose mutations require If-Match. */
  isMutationEndpoint: (url: string) => boolean
  idFromUrl: (url: string) => string | null
  /** Resource id for a mutation — usually from the URL, but delivery receipts carry it in the body. */
  idForMutation: (url: string, body: unknown) => string | null
  conflict: StatusMessages // 412
  missing: StatusMessages // 428
}

function jobIdFromUrl(url: string): string | null {
  return url.match(/\/api\/job\/jobs\/([0-9a-f-]{36})/i)?.[1] ?? null
}

function poIdFromUrl(url: string): string | null {
  return url.match(/\/api\/purchasing\/purchase-orders\/([0-9a-f-]{36})/i)?.[1] ?? null
}

const JOB_MUTATION_PATTERNS = [
  /\/api\/job\/jobs\/[^/]+\/?$/, // PUT/PATCH/DELETE on job detail
  /\/api\/job\/jobs\/[^/]+\/events/, // POST events
  /\/api\/job\/jobs\/[^/]+\/undo-change/, // POST undo change
  /\/api\/job\/jobs\/[^/]+\/quote\/accept/, // POST quote accept
]

const PO_MUTATION_PATTERNS = [
  /\/api\/purchasing\/purchase-orders\/[^/]+\/?$/, // PATCH on PO detail
  /\/api\/purchasing\/delivery-receipts\/?$/, // POST delivery receipts
  // POST allocation delete. It decrements received_quantity and recomputes the
  // PO status, so it is a PO mutation and carries the precondition. The first
  // pattern cannot reach it: [^/] stops at the slash before /lines/.
  // Opus: /events/ and /email/ are deliberately absent — neither touches
  // PurchaseOrder.updated_at, so a precondition there would 412 a comment
  // whenever anyone else edited the PO.
  /\/api\/purchasing\/purchase-orders\/[^/]+\/lines\/[^/]+\/allocations\/delete\/?$/,
]

function poIdForMutation(url: string, body: unknown): string | null {
  if (url.includes('/api/purchasing/delivery-receipts/')) {
    try {
      const parsed: unknown = typeof body === 'string' ? JSON.parse(body) : body
      if (typeof parsed === 'object' && parsed !== null && 'purchase_order_id' in parsed) {
        const id = (parsed as { purchase_order_id?: unknown }).purchase_order_id
        return typeof id === 'string' ? id : null
      }
    } catch {
      return null
    }
    return null
  }
  return poIdFromUrl(url)
}

const RULES: readonly ResourceRule[] = [
  {
    kind: 'job',
    isVersionedEndpoint: (url) =>
      /\/api\/job\/jobs\//.test(url) &&
      !url.includes('/jobs/status-choices') &&
      !url.includes('/jobs/weekly-metrics'),
    isMutationEndpoint: (url) => JOB_MUTATION_PATTERNS.some((pattern) => pattern.test(url)),
    idFromUrl: jobIdFromUrl,
    idForMutation: (url) => jobIdFromUrl(url),
    conflict: {
      toast: 'This job was updated by another user. Data reloaded.',
      error: 'This job was updated by another user. Data reloaded. Please retry your changes.',
    },
    missing: {
      toast: 'Missing version information. Job data reloaded.',
      error: 'Missing version information. Job data reloaded. Please retry your changes.',
    },
  },
  {
    kind: 'po',
    isVersionedEndpoint: (url) => /\/api\/purchasing\/purchase-orders\//.test(url),
    isMutationEndpoint: (url) => PO_MUTATION_PATTERNS.some((pattern) => pattern.test(url)),
    idFromUrl: poIdFromUrl,
    idForMutation: poIdForMutation,
    conflict: {
      toast: 'This purchase order was updated elsewhere. Data reloaded.',
      error:
        'This purchase order was updated elsewhere. Data reloaded. Please review and resubmit.',
    },
    missing: {
      toast:
        'Missing version information. Purchase order data has been reloaded - please review before retrying your update.',
      error:
        'Missing version information. Purchase order data reloaded. Please review and resubmit.',
    },
  },
]

// --- Query invalidator registry ---

type QueryInvalidator = (id: string) => Promise<unknown>

const invalidators = new Map<ResourceKind, QueryInvalidator>()

/**
 * Register how to refetch a resource's query after a 412/428, keyed by kind.
 * Features own their query keys, so they register the resolver (e.g. the job
 * feature invalidates its job-detail queryOptions for the conflicting id).
 */
export function registerConcurrencyInvalidator(
  kind: ResourceKind,
  invalidate: QueryInvalidator,
): void {
  invalidators.set(kind, invalidate)
}

// --- Interceptors (structural types; axios objects satisfy them) ---

const MUTATING_METHODS = new Set(['post', 'put', 'patch', 'delete'])

export interface ConcurrencyRequest {
  url?: string
  method?: string
  data?: unknown
  headers: Record<string, unknown>
}

/** Request interceptor: attach If-Match on mutating Job/PO requests. */
export function attachIfMatch<T extends ConcurrencyRequest>(config: T): T {
  const url = config.url ?? ''
  const method = (config.method ?? 'get').toLowerCase()
  if (!MUTATING_METHODS.has(method)) {
    return config
  }
  // Retried requests must preserve the precondition under which the user made
  // the change. Replacing it with a newer cached ETag could apply an old edit
  // to state the user never saw.
  if (Object.keys(config.headers).some((header) => header.toLowerCase() === 'if-match')) {
    return config
  }
  for (const rule of RULES) {
    if (!rule.isMutationEndpoint(url)) continue
    const id = rule.idForMutation(url, config.data)
    if (!id) continue
    const etag = getEtag(etagKey(rule.kind, id))
    if (etag) {
      config.headers['If-Match'] = etag
    }
    break
  }
  return config
}

export interface ConcurrencyResponse {
  headers: Record<string, unknown>
  // `data` is the REQUEST body axios echoes back on the response config; it is
  // how a body-addressed mutation's resource id is recovered (see below).
  config: { url?: string; data?: unknown }
}

/** Response interceptor: capture strong resource versions from Job/PO endpoints. */
export function captureResourceVersion<T extends ConcurrencyResponse>(response: T): T {
  const url = response.config.url ?? ''
  const version = strongResourceVersion(response.headers)
  if (!version) {
    return response
  }
  for (const rule of RULES) {
    // Opus: a mutation endpoint counts as versioned here even when the read
    // rule does not match it. Gating on isVersionedEndpoint alone dropped the
    // fresh ETag that POST /api/purchasing/delivery-receipts/ returns, because
    // its URL carries no /purchase-orders/<uuid>/ segment — so every receipt
    // left a stale version in the store and 412'd the next PO mutation until a
    // refetch landed.
    if (!rule.isVersionedEndpoint(url) && !rule.isMutationEndpoint(url)) continue
    // The URL is tried first and the body only as a fallback: a URL-addressed
    // response is unambiguous, while the body form exists solely for endpoints
    // that carry the id there.
    const id = rule.idFromUrl(url) ?? rule.idForMutation(url, response.config.data)
    if (id) {
      setEtag(etagKey(rule.kind, id), version)
    }
  }
  return response
}

function isRecord(value: unknown): value is Record<PropertyKey, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * Response error interceptor: on 412/428 for a Job/PO mutation, refetch the
 * resource via the registered invalidator, toast with a Retry action, and
 * reject with ConcurrencyError. Everything else passes through untouched.
 */
export async function handleConcurrencyFailure(error: unknown): Promise<never> {
  const failure = isRecord(error) ? error : {}
  const response = isRecord(failure.response) ? failure.response : undefined
  const config = isRecord(failure.config) ? failure.config : undefined
  const status = typeof response?.status === 'number' ? response.status : undefined
  if (status !== 412 && status !== 428) {
    throw error
  }

  const url = typeof config?.url === 'string' ? config.url : ''
  const match = matchMutationRule(url, config?.data)
  if (!match) {
    throw error
  }
  const { rule, id } = match

  const messages = status === 412 ? rule.conflict : rule.missing
  const invalidate = invalidators.get(rule.kind)
  if (invalidate) {
    try {
      await invalidate(id)
    } catch {
      // Refetch failure must not mask the actionable concurrency error.
    }
  }

  toast.error(messages.toast, {
    duration: Infinity, // Don't auto-dismiss
    action: {
      label: 'Retry',
      onClick: () => {
        emitConcurrencyRetry({ kind: rule.kind, id })
      },
    },
  })

  throw new ConcurrencyError(messages.error, rule.kind, id)
}

/** First rule whose mutation-URL pattern matches and yields a resource id. */
function matchMutationRule(
  url: string,
  data: unknown,
): { rule: (typeof RULES)[number]; id: string } | null {
  for (const rule of RULES) {
    if (!rule.isMutationEndpoint(url)) continue
    const id = rule.idForMutation(url, data)
    if (id) return { rule, id }
  }
  return null
}
