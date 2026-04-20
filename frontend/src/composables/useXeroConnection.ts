import { ref, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { api } from '@/api/client'

/**
 * Lightweight composable for components that only need to know whether Xero
 * is currently connected (e.g. to gate "Create Quote" / "Create Invoice"
 * buttons).
 *
 * Distinct from the heavier `useXeroAuth` composable, which also owns the
 * SSE sync stream, entity progress state, and login/logout flow.
 *
 * Semantics:
 * - `{ connected: false }` from the ping endpoint is a legitimate state
 *   (user simply hasn't connected Xero yet) and must NOT produce a toast —
 *   otherwise we'd fire one on every page load for unconnected users.
 * - A thrown exception (network error, backend 500, etc.) IS a real failure
 *   and DOES produce a toast so the user knows the Xero-gated buttons may
 *   be incorrectly disabled because status is unknown.
 */
export function useXeroConnection() {
  const xeroConnected = ref(false)

  onMounted(async () => {
    try {
      const pingRes = await api.xero_ping_retrieve()
      xeroConnected.value = !!pingRes?.connected
    } catch (err) {
      console.error('Failed to check Xero connection status:', err)
      toast.error('Unable to check Xero connection status')
      xeroConnected.value = false
    }
  })

  return { xeroConnected }
}
