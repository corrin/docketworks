<template>
  <div id="app" class="min-h-screen bg-background text-foreground">
    <router-view />
    <Toaster />
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import { onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { Toaster } from '@/components/ui/sonner'
import 'vue-sonner/style.css'
import { useFeatureFlags } from './stores/feature-flags'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { dataFreshness } from '@/composables/useDataFreshness'

const authStore = useAuthStore()

debugLog(useFeatureFlags().isCostingApiEnabled)

function refreshDataIfVisible(): void {
  if (document.visibilityState !== 'visible') return
  dataFreshness.checkFreshness().catch((err) => {
    debugLog('[App] data-freshness check failed:', err)
  })
}

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
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', refreshDataIfVisible)
})
</script>
