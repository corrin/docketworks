/**
 * Concurrency retry coordination via DOM events
 *
 * Emits and listens for a global event when the user clicks "Retry" in the toast.
 * Components with pending autosave can subscribe per jobId and call autosave.flush('retry-click')
 * only when the user explicitly approves the retry.
 */

const EVENT_NAME = 'concurrency-retry'

interface ConcurrencyRetryDetail {
  jobId: string
}

/**
 * Emit a retry request for a given jobId
 */
export function emitConcurrencyRetry(jobId: string): void {
  try {
    const evt = new CustomEvent<ConcurrencyRetryDetail>(EVENT_NAME, { detail: { jobId } })
    window.dispatchEvent(evt)
  } catch {
    // noop - older browsers would not be a concern in this stack
  }
}

/**
 * Subscribe to retry requests for a given jobId.
 * Returns an unsubscribe function to remove the listener.
 */
export function onConcurrencyRetry(jobId: string, handler: () => void): () => void {
  const listener = (e: Event) => {
    const evt = e as CustomEvent<ConcurrencyRetryDetail>
    if (evt.detail?.jobId === jobId) {
      handler()
    }
  }
  window.addEventListener(EVENT_NAME, listener as EventListener)
  return () => window.removeEventListener(EVENT_NAME, listener as EventListener)
}
