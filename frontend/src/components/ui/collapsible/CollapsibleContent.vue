<template>
  <Transition
    name="collapsible"
    enter-active-class="transition-all duration-200 ease-out"
    leave-active-class="transition-all duration-200 ease-in"
    enter-from-class="opacity-0 transform scale-95"
    enter-to-class="opacity-100 transform scale-100"
    leave-from-class="opacity-100 transform scale-100"
    leave-to-class="opacity-0 transform scale-95"
  >
    <div v-if="isOpen" class="collapsible-content">
      <slot />
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { inject, type Ref } from 'vue'

// Inject the open state from parent Collapsible
const isOpen = inject<Ref<boolean>>('collapsible-open')

if (!isOpen) {
  throw new Error('CollapsibleContent must be used within a Collapsible component')
}
</script>

<style scoped>
.collapsible-content {
  overflow: hidden;
}

/* Custom transition classes for smoother animations */
.collapsible-enter-active,
.collapsible-leave-active {
  transition: all 0.2s ease;
}

.collapsible-enter-from {
  opacity: 0;
  max-height: 0;
  transform: translateY(-10px);
}

.collapsible-enter-to {
  opacity: 1;
  max-height: 1000px;
  transform: translateY(0);
}

.collapsible-leave-from {
  opacity: 1;
  max-height: 1000px;
  transform: translateY(0);
}

.collapsible-leave-to {
  opacity: 0;
  max-height: 0;
  transform: translateY(-10px);
}
</style>
