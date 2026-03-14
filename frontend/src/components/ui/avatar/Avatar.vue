<!-- eslint-disable vue/multi-word-component-names -->
<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { AvatarRoot } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <div class="app-avatar">
    <AvatarRoot
      data-slot="avatar"
      :class="cn('relative flex size-8 shrink-0 overflow-hidden rounded-full', props.class)"
    >
      <slot />
    </AvatarRoot>
  </div>
</template>
