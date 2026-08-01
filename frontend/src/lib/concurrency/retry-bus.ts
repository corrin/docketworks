/**
 * Typed pub/sub for concurrency "Retry" clicks, replacing v1's window
 * CustomEvents (useConcurrencyEvents / usePoConcurrencyEvents).
 *
 * The 412/428 interceptor shows a toast with a Retry action; components with a
 * pending save subscribe per resource and flush only when the user approves.
 */
export type ResourceKind = 'job' | 'po'

export interface ConcurrencyRetryEvent {
  kind: ResourceKind
  id: string
}

type Handler = (event: ConcurrencyRetryEvent) => void

const handlers = new Set<Handler>()

export function emitConcurrencyRetry(event: ConcurrencyRetryEvent): void {
  // Copy before iterating so handlers that unsubscribe mid-emit are safe.
  for (const handler of [...handlers]) {
    handler(event)
  }
}

/** Subscribe to every retry event. Returns an unsubscribe function. */
export function subscribeConcurrencyRetry(handler: Handler): () => void {
  handlers.add(handler)
  return () => {
    handlers.delete(handler)
  }
}

/** Subscribe to retry events for one resource (v1's per-jobId subscribe). */
export function onConcurrencyRetry(
  kind: ResourceKind,
  id: string,
  handler: () => void,
): () => void {
  return subscribeConcurrencyRetry((event) => {
    if (event.kind === kind && event.id === id) {
      handler()
    }
  })
}
