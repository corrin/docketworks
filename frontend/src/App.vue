<template>
  <div id="app" class="min-h-screen bg-background text-foreground">
    <router-view />
    <Toaster />
  </div>
</template>

<script setup lang="ts">
import debug from 'debug'

import { onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { Toaster } from '@/components/ui/sonner'
import 'vue-sonner/style.css'
import { useFeatureFlags } from './stores/feature-flags'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { useNotebookLmLinksStore } from '@/stores/notebookLmLinks'
import { dataFreshness } from '@/composables/useDataFreshness'
import {
  flushSessionReplay,
  reportFrontendError,
  startSessionReplay,
  stopSessionReplay,
} from '@/services/sessionReplayService'

const log = debug('app:root')

const authStore = useAuthStore()

log('costing API enabled: %o', useFeatureFlags().isCostingApiEnabled)

function refreshDataIfVisible(): void {
  if (document.visibilityState !== 'visible') return
  // Skip when unauthenticated (login screen, expired session) — otherwise
  // every tab-focus would 401 against /api/data-versions/ and persist an
  // AppError per ADR 0019.
  if (!authStore.isAuthenticated) return
  dataFreshness.checkFreshness().catch((err) => {
    log('data-freshness check failed:', err)
  })
}

function flushReplayIfHidden(): void {
  if (document.visibilityState !== 'hidden') return
  flushSessionReplay().catch((err) => {
    log('session replay visibility flush failed:', err)
  })
}

function flushReplayBeforeUnload(): void {
  void flushSessionReplay()
}

function captureFrontendError(event: ErrorEvent | PromiseRejectionEvent): void {
  reportFrontendError(event).catch((err) => {
    log('frontend error replay report failed:', err)
  })
}

function syncSessionReplayWithAuth(isAuthenticated: boolean): void {
  if (isAuthenticated) {
    startSessionReplay().catch((err) => {
      log('session replay start failed:', err)
    })
  } else {
    stopSessionReplay().catch((err) => {
      log('session replay stop failed:', err)
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
      log('Before loading company defaults:', companyDefaultsStore.companyDefaults)
      await companyDefaultsStore.loadCompanyDefaults()
      log('After loading company defaults:', companyDefaultsStore.companyDefaults)
      const notebookLmLinksStore = useNotebookLmLinksStore()
      await notebookLmLinksStore.loadLinks()
      // Establish baseline dataset versions; subscribers don't fire on first
      // observation, only on subsequent changes.
      dataFreshness.checkFreshness().catch((err) => {
        log('initial data-freshness check failed:', err)
      })
    }
  } catch (error) {
    log('Failed to initialize auth or company defaults on app start:', error)
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
    log('session replay stop failed:', err)
  })
})
</script>
