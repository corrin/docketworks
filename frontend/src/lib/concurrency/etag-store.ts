/**
 * ETag store for optimistic concurrency (ADR 0003).
 *
 * One generic module-level map keyed by resource key (`<kind>:<id>`) prevents
 * job and purchase-order ETag storage from becoming separate implementations.
 */
const etags = new Map<string, string>()

export function etagKey(kind: string, id: string): string {
  return `${kind}:${id}`
}

export function getEtag(key: string): string | null {
  return etags.get(key) ?? null
}

export function setEtag(key: string, etag: string): void {
  etags.set(key, etag)
}

export function deleteEtag(key: string): void {
  etags.delete(key)
}

/** Drop all stored ETags (logout, tests). */
export function clearEtags(): void {
  etags.clear()
}
