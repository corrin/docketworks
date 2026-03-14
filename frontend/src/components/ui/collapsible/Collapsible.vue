<!-- eslint-disable vue/multi-word-component-names -->
<template>
  <div class="collapsible">
    <slot />
  </div>
</template>

<script setup lang="ts">
import { provide, ref, watch, type Ref } from 'vue'

interface Props {
  open?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  open: false,
})

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

// Create reactive open state that can be controlled externally
const isOpen: Ref<boolean> = ref(props.open)

// Watch for prop changes and update internal state
watch(
  () => props.open,
  (newValue) => {
    isOpen.value = newValue
  },
)

// Watch internal state and emit changes
watch(isOpen, (newValue) => {
  emit('update:open', newValue)
})

// Provide the open state to children
provide('collapsible-open', isOpen)
provide('collapsible-toggle', () => {
  isOpen.value = !isOpen.value
})
</script>
