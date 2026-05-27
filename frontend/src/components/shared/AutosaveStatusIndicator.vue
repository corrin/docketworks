<script setup lang="ts">
import { computed } from 'vue'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-vue-next'
import { useAutosaveStatusStore } from '@/stores/autosaveStatus'

const store = useAutosaveStatusStore()

const status = computed(() => store.aggregate)
const isVisible = computed(() => !!status.value)
const isWorking = computed(
  () => status.value?.state === 'saving' || status.value?.state === 'pending',
)
const isSaved = computed(() => status.value?.state === 'saved')
const isError = computed(() => status.value?.state === 'error')

const label = computed(() => {
  if (isWorking.value) return 'Saving...'
  if (isError.value) return status.value?.message || 'Save failed'
  if (isSaved.value) return 'Saved'
  return ''
})
</script>

<template>
  <div
    data-automation-id="AutosaveStatusIndicator"
    aria-live="polite"
    aria-atomic="true"
    class="hidden sm:flex min-w-[84px] items-center justify-end text-xs"
  >
    <Transition
      enter-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-150"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="isVisible"
        class="flex items-center gap-1.5 whitespace-nowrap"
        :class="isError ? 'text-red-600' : 'text-gray-500'"
      >
        <Loader2 v-if="isWorking" class="h-3.5 w-3.5 animate-spin" />
        <CheckCircle2 v-else-if="isSaved" class="h-3.5 w-3.5 text-emerald-600" />
        <AlertCircle v-else-if="isError" class="h-3.5 w-3.5" />
        <span>{{ label }}</span>
      </div>
    </Transition>
  </div>
</template>
