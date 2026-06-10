/**
 * Safe wrapper around `sessionStorage`.
 *
 * `sessionStorage` access can throw in environments where storage is
 * unavailable or blocked: private browsing modes, sandboxed iframes, or
 * browsers with storage disabled. For the UI conveniences stored here
 * (active job selection, board mode preference), silent degradation is the
 * INTENDED behavior — the app simply behaves as if nothing was persisted.
 *
 * This is the single sanctioned place where storage errors are swallowed.
 * The project is otherwise fail-early; do not copy this pattern for other
 * error sources.
 */
export const safeSessionStorage = {
  get(key: string): string | null {
    try {
      return sessionStorage.getItem(key)
    } catch {
      return null
    }
  },
  set(key: string, value: string): void {
    try {
      sessionStorage.setItem(key, value)
    } catch {
      // Intentional no-op — storage unavailable (see doc comment above)
    }
  },
  remove(key: string): void {
    try {
      sessionStorage.removeItem(key)
    } catch {
      // Intentional no-op — storage unavailable (see doc comment above)
    }
  },
}
