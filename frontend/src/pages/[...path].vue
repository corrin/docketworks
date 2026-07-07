<template>
  <main
    data-automation-id="NotFound-page"
    class="min-h-screen bg-slate-50 text-slate-900 flex items-center justify-center px-4"
  >
    <section class="w-full max-w-md space-y-5 text-center">
      <div class="space-y-2">
        <p class="text-5xl font-bold tracking-tight">404</p>
        <h1 class="text-2xl font-semibold">Page not found</h1>
        <p class="text-sm leading-6 text-slate-600">
          No page exists at <code class="rounded bg-slate-200 px-1 py-0.5">{{ attemptedPath }}</code
          >.
        </p>
        <p class="text-sm leading-6 text-slate-600">
          If you followed a bookmark, it points at a page that no longer exists.
        </p>
      </div>

      <RouterLink
        to="/"
        class="inline-flex h-10 items-center rounded-md bg-slate-900 px-4 text-sm font-medium text-white hover:bg-slate-800"
      >
        Go to home
      </RouterLink>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const attemptedPath = computed(() => {
  const path = route.params.path
  const joined = Array.isArray(path) ? `/${path.join('/')}` : `/${path}`
  return joined
})
</script>
