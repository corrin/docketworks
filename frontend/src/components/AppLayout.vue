<template>
  <div class="h-screen bg-gray-50 flex flex-col">
    <div class="flex-shrink-0">
      <AppNavbar />
    </div>

    <main :class="mainClasses">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
import AppNavbar from './AppNavbar.vue'
import { useRoute } from 'vue-router'
import { computed, watch, onMounted, onBeforeUnmount } from 'vue'

const route = useRoute()

const allowVerticalScroll = computed(() => route.meta.allowScroll === true)

const mainClasses = computed(() => [
  'flex-1 pt-12 md:pt-8 lg:pt-14 flex flex-col min-h-0',
  allowVerticalScroll.value ? 'overflow-y-auto' : 'overflow-y-hidden',
])

let originalBodyOverflow = ''
let originalHtmlOverflow = ''

const applyGlobalOverflow = (allow: boolean) => {
  if (typeof window === 'undefined') return
  const value = allow ? 'auto' : 'hidden'
  document.body.style.overflowY = value
  document.documentElement.style.overflowY = value
}

onMounted(() => {
  if (typeof window === 'undefined') return
  originalBodyOverflow = document.body.style.overflowY
  originalHtmlOverflow = document.documentElement.style.overflowY
  applyGlobalOverflow(allowVerticalScroll.value)
})

watch(
  () => allowVerticalScroll.value,
  (allow) => {
    applyGlobalOverflow(allow)
  },
)

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return
  document.body.style.overflowY = originalBodyOverflow
  document.documentElement.style.overflowY = originalHtmlOverflow
})
</script>
