import { useEffect, useState } from 'react'

/** The typing pause before a search box asks the server. */
export const SEARCH_DEBOUNCE_MS = 300
// Opus: Mirrors apps/job/services/job_search.MIN_SEARCH_TERM_LENGTH: below this a
// substring match is not selective enough to be worth a round trip, and the
// job endpoint refuses it with a 400. The company and address lookups share it.
export const MIN_SEARCH_TERM_LENGTH = 3

/** Debounces a changing value — a search box feeding a query key is the
    common case. Not for URL/history-driven debouncing (KanbanSearchInput),
    which has its own hydrate/replace semantics this hook does not cover. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
