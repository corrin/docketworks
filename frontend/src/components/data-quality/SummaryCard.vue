<template>
  <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <p class="text-sm text-slate-600">{{ label }}</p>
    <p class="mt-1 text-2xl font-bold" :class="toneClass">{{ value }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  label: string
  value: number
  tone: 'amber' | 'green' | 'red'
}>()

const toneClass = computed(
  () =>
    ({
      amber: 'text-amber-700',
      green: 'text-green-700',
      red: 'text-red-700',
    })[props.tone],
)
</script>
