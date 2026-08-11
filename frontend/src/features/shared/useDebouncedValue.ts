import { useEffect, useState } from 'react'

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
