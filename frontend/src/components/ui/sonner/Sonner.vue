<!-- eslint-disable vue/multi-word-component-names -->
<script lang="ts" setup>
import { Toaster as Sonner, type ToasterProps } from 'vue-sonner'
import { onMounted, ref } from 'vue'

const props = defineProps<ToasterProps>()
const isMounted = ref(false)

onMounted(() => {
  isMounted.value = true
})
</script>

<template>
  <Sonner
    v-if="isMounted"
    class="toaster group"
    v-bind="props"
    :style="{
      '--normal-bg': 'var(--popover)',
      '--normal-text': 'var(--popover-foreground)',
      '--normal-border': 'var(--border)',
    }"
  />
</template>
