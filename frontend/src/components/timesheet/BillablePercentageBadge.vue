<template>
  <div
    class="inline-flex items-center justify-center px-2 py-1 rounded text-xs font-semibold min-w-[50px]"
    :class="badgeClass"
    :title="tooltipText"
  >
    {{ displayValue }}
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  percentage?: number
}>()

const numericPercentage = computed(() => {
  if (props.percentage === undefined || props.percentage === null) return null
  return isNaN(props.percentage) ? null : props.percentage
})

const displayValue = computed(() => {
  if (numericPercentage.value === null) return '--'
  return `${numericPercentage.value.toFixed(1)}%`
})

const badgeClass = computed(() => {
  if (numericPercentage.value === null) return 'bg-gray-100 text-gray-600'
  if (numericPercentage.value >= 80) return 'bg-green-500 text-white'
  if (numericPercentage.value >= 60) return 'bg-green-100 text-green-800'
  if (numericPercentage.value >= 40) return 'bg-yellow-100 text-yellow-800'
  return 'bg-red-100 text-red-800'
})

const tooltipText = computed(() => {
  if (numericPercentage.value === null) return 'No data available'
  if (numericPercentage.value >= 80) return 'Excellent billable percentage'
  if (numericPercentage.value >= 60) return 'Good billable percentage'
  if (numericPercentage.value >= 40) return 'Fair billable percentage'
  return 'Low billable percentage'
})
</script>
