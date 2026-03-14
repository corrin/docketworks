// Debug logging - enable via localStorage.setItem('debug', 'true')
const isDevelopment = import.meta.env.MODE === 'development'

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
