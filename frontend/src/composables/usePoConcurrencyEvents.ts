/**
 * Purchase Order concurrency retry coordination via DOM events
 *
 * Emits and listens for a global event when the user clicks "Retry" in the toast.
 * Components with pending autosave can subscribe per poId and call autosave.flush('retry-click')
 * only when the user explicitly approves the retry.
 */

const EVENT_NAME = 'po-concurrency-retry'

interface PoConcurrencyRetryDetail {
  poId: string
}

/**
 * Emit a retry request for a given purchase order ID
 */
export function emitPoConcurrencyRetry(poId: string): void {
  try {
    const evt = new CustomEvent<PoConcurrencyRetryDetail>(EVENT_NAME, { detail: { poId } })
    window.dispatchEvent(evt)
  } catch {
    // noop - older browsers would not be a concern in this stack
  }
}

/**
 * Subscribe to retry requests for a given purchase order ID.
 * Returns an unsubscribe function to remove the listener.
 */
export function onPoConcurrencyRetry(poId: string, handler: () => void): () => void {
  const listener = (e: Event) => {
    const evt = e as CustomEvent<PoConcurrencyRetryDetail>
    if (evt.detail?.poId === poId) {
      handler()
    }
  }
  window.addEventListener(EVENT_NAME, listener as EventListener)
  return () => window.removeEventListener(EVENT_NAME, listener as EventListener)
}
