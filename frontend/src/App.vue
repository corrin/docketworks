<template>
  <div id="app" class="min-h-screen bg-background text-foreground">
    <router-view />
    <Toaster />
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import { onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { Toaster } from '@/components/ui/sonner'
import 'vue-sonner/style.css'
import { useFeatureFlags } from './stores/feature-flags'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { dataFreshness } from '@/composables/useDataFreshness'
import {
  flushSessionReplay,
  reportFrontendError,
  startSessionReplay,
  stopSessionReplay,
} from '@/services/sessionReplayService'

const authStore = useAuthStore()

debugLog(useFeatureFlags().isCostingApiEnabled)

function refreshDataIfVisible(): void {
  if (document.visibilityState !== 'visible') return
  // Skip when unauthenticated (login screen, expired session) — otherwise
  // every tab-focus would 401 against /api/data-versions/ and persist an
  // AppError per ADR 0019.
  if (!authStore.isAuthenticated) return
  dataFreshness.checkFreshness().catch((err) => {
    debugLog('[App] data-freshness check failed:', err)
  })
}

function flushReplayIfHidden(): void {
  if (document.visibilityState !== 'hidden') return
  flushSessionReplay().catch((err) => {
    debugLog('[App] session replay visibility flush failed:', err)
  })
}

function flushReplayBeforeUnload(): void {
  void flushSessionReplay()
}

function captureFrontendError(event: ErrorEvent | PromiseRejectionEvent): void {
  reportFrontendError(event).catch((err) => {
    debugLog('[App] frontend error replay report failed:', err)
  })
}

function syncSessionReplayWithAuth(isAuthenticated: boolean): void {
  if (isAuthenticated) {
    startSessionReplay().catch((err) => {
      debugLog('[App] session replay start failed:', err)
    })
  } else {
    stopSessionReplay().catch((err) => {
      debugLog('[App] session replay stop failed:', err)
    })
  }
}

const stopAuthReplayWatcher = watch(
  () => authStore.isAuthenticated,
  (isAuthenticated) => {
    syncSessionReplayWithAuth(isAuthenticated)
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    const isAuthenticated = await authStore.initializeAuth()
    if (isAuthenticated) {
      const companyDefaultsStore = useCompanyDefaultsStore()
      debugLog('[App] Before loading company defaults:', companyDefaultsStore.companyDefaults)
      await companyDefaultsStore.loadCompanyDefaults()
      debugLog('[App] After loading company defaults:', companyDefaultsStore.companyDefaults)
      // Establish baseline dataset versions; subscribers don't fire on first
      // observation, only on subsequent changes.
      dataFreshness.checkFreshness().catch((err) => {
        debugLog('[App] initial data-freshness check failed:', err)
      })
    }
  } catch (error) {
    debugLog('Failed to initialize auth or company defaults on app start:', error)
  }
  document.addEventListener('visibilitychange', refreshDataIfVisible)
  document.addEventListener('visibilitychange', flushReplayIfHidden)
  window.addEventListener('beforeunload', flushReplayBeforeUnload)
  window.addEventListener('error', captureFrontendError)
  window.addEventListener('unhandledrejection', captureFrontendError)
})

onUnmounted(() => {
  stopAuthReplayWatcher()
  document.removeEventListener('visibilitychange', refreshDataIfVisible)
  document.removeEventListener('visibilitychange', flushReplayIfHidden)
  window.removeEventListener('beforeunload', flushReplayBeforeUnload)
  window.removeEventListener('error', captureFrontendError)
  window.removeEventListener('unhandledrejection', captureFrontendError)
  stopSessionReplay().catch((err) => {
    debugLog('[App] session replay stop failed:', err)
  })
})
</script>
