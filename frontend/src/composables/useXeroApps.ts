import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { z } from 'zod'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { debugLog } from '@/utils/debug'

export type XeroApp = z.infer<typeof schemas.XeroApp>

const POLL_INTERVAL_MS = 60_000

/**
 * Reactive view of the workflow XeroApp collection.
 *
 * Auto-polls every 60s while a consuming component is mounted so badges and
 * tables stay in sync with backend snapshot updates. Pass `autoPoll = false`
 * for one-shot consumers (e.g. the settings page that already refreshes after
 * mutations) to skip the interval.
 */
export function useXeroApps(autoPoll: boolean = true) {
  const rows = ref<XeroApp[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const activeApp = computed<XeroApp | null>(
    () => rows.value.find((r) => r.is_active === true) ?? null,
  )

  let intervalId: ReturnType<typeof setInterval> | null = null

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      rows.value = await api.workflow_xero_apps_list()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load Xero apps.'
      error.value = message
      debugLog('[useXeroApps] refresh failed:', err)
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    refresh()
    if (autoPoll) {
      intervalId = setInterval(() => {
        refresh()
      }, POLL_INTERVAL_MS)
    }
  })

  onUnmounted(() => {
    if (intervalId !== null) {
      clearInterval(intervalId)
      intervalId = null
    }
  })

  return {
    rows,
    loading,
    error,
    refresh,
    activeApp,
  }
}
