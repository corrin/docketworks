<template>
  <main class="min-h-screen bg-slate-50 text-slate-900 flex items-center justify-center px-4">
    <section class="w-full max-w-md space-y-5">
      <div class="space-y-2">
        <h1 class="text-2xl font-semibold">Connection interrupted</h1>
        <p class="text-sm leading-6 text-slate-600">
          DocketWorks could not confirm your session. This usually means the page load or network
          request was interrupted.
        </p>
      </div>

      <button
        type="button"
        class="inline-flex h-10 items-center gap-2 rounded-md bg-slate-900 px-4 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="isRetrying"
        @click="retrySessionCheck"
      >
        <RefreshCw :class="['h-4 w-4', isRetrying ? 'animate-spin' : '']" />
        <span>{{ isRetrying ? 'Checking...' : 'Retry' }}</span>
      </button>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshCw } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const isRetrying = ref(false)

const redirectPath = computed(() => {
  const redirect = route.query.redirect
  if (typeof redirect === 'string' && redirect.startsWith('/')) return redirect
  return authStore.defaultRoutePath
})

async function retrySessionCheck(): Promise<void> {
  isRetrying.value = true
  try {
    const status = await authStore.checkSession()
    if (status === 'authenticated') {
      await router.replace(redirectPath.value)
    } else if (status === 'unauthenticated') {
      await router.replace({ name: 'login', query: { redirect: redirectPath.value } })
    }
  } finally {
    isRetrying.value = false
  }
}
</script>
