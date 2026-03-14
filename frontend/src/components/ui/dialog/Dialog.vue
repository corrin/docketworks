<!-- eslint-disable vue/multi-word-component-names -->
<script setup lang="ts">
import {
  DialogRoot,
  type DialogRootEmits,
  type DialogRootProps,
  useForwardPropsEmits,
} from 'reka-ui'

const props = defineProps<DialogRootProps>()
const emits = defineEmits<DialogRootEmits>()

const forwarded = useForwardPropsEmits(props, emits)
</script>

<template>
  <div class="app-dialog">
    <DialogRoot data-slot="dialog" v-bind="forwarded">
      <slot />
    </DialogRoot>
  </div>
</template>
