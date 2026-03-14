<!-- eslint-disable vue/multi-word-component-names -->
<script setup lang="ts">
import type { PopoverRootEmits, PopoverRootProps } from 'reka-ui'
import { PopoverRoot, useForwardPropsEmits } from 'reka-ui'

const props = defineProps<PopoverRootProps>()
const emits = defineEmits<PopoverRootEmits>()

const forwarded = useForwardPropsEmits(props, emits)
</script>

<template>
  <div class="app-popover">
    <PopoverRoot data-slot="popover" v-bind="forwarded">
      <slot />
    </PopoverRoot>
  </div>
</template>
