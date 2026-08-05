/**
 * Typed pub/sub for concurrency "Retry" clicks; a shared bus prevents job and
 * PO retry behavior from diverging.
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
  // Snapshot before iterating: handlers added mid-emit must not receive this event.
  for (const handler of Array.from(handlers)) {
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

/** Subscribe to retry events for one resource key. */
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
