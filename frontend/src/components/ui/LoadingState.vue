<template>
  <div v-if="isLoading && !hasData" :class="loadingClasses" :style="{ minHeight }">
    <div
      v-if="showSpinner"
      class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"
    ></div>
    <span>{{ loadingMessage }}</span>
  </div>

  <div v-else-if="!isLoading && !hasData" :class="emptyClasses" :style="{ minHeight }">
    <div v-if="emptyIcon !== 'none'" class="mb-2">
      <slot name="empty-icon">
        <svg
          class="w-8 h-8 mx-auto text-gray-300"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
      </slot>
    </div>
    <p>{{ emptyMessage }}</p>
    <slot name="empty-actions"></slot>
  </div>

  <slot v-else></slot>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  isLoading: boolean
  hasData: boolean
  loadingMessage?: string
  emptyMessage?: string
  emptyIcon?: string
  showSpinner?: boolean
  centered?: boolean
  minHeight?: string
}

const props = withDefaults(defineProps<Props>(), {
  loadingMessage: 'Loading data, please wait',
  emptyMessage: 'No data found',
  emptyIcon: 'none',
  showSpinner: true,
  centered: true,
  minHeight: 'auto',
})

const loadingClasses = computed(() => [
  'flex items-center gap-2 text-gray-500 py-4',
  props.centered ? 'justify-center' : '',
])

const emptyClasses = computed(() => ['text-gray-500 py-4', props.centered ? 'text-center' : ''])
</script>
