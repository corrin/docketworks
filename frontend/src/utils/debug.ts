// Debug logging - enable via localStorage.setItem('debug', 'true')
// `import.meta.env` is injected by Vite; when this module is loaded outside Vite
// (e.g. Playwright tests importing a sibling utility), fall back to `off`.
const isDevelopment = (() => {
  try {
    return import.meta.env?.MODE === 'development'
  } catch {
    return false
  }
})()

function isEnabled(): boolean {
  if (isDevelopment) return true
  try {
    return localStorage.getItem('debug') === 'true'
  } catch {
    return false
  }
}

export function debugLog(...args: unknown[]): void {
  if (isEnabled()) {
    console.log('[DEBUG]', ...args)
  }
}

export const isDebugEnabled = isEnabled
