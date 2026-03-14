<template>
  <span class="inline-flex items-center font-bold text-xs" :class="textColorClass">
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { statusColorMap } from '@/utils/statusMappings'

interface Props {
  label: string
  status: string
  size?: 'xs' | 'sm' | 'md' | 'lg'
}

const props = withDefaults(defineProps<Props>(), {
  size: 'sm',
})

const textColorClass = computed(() => {
  return statusColorMap[props.status] || 'text-gray-700'
})
</script>

<style scoped>
.badge-shadow {
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}
</style>
