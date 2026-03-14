<!-- eslint-disable vue/multi-word-component-names -->
<script lang="ts" setup>
import type { DrawerRootEmits, DrawerRootProps } from 'vaul-vue'
import { DrawerRoot } from 'vaul-vue'

const props = withDefaults(defineProps<DrawerRootProps>(), {
  shouldScaleBackground: true,
})

const emit = defineEmits<DrawerRootEmits>()
</script>

<template>
  <!-- 'as any' needed: vaul-vue DrawerRootProps type mismatch with Vue's v-bind. Standard shadcn-vue pattern. -->
  <DrawerRoot data-slot="drawer" v-bind="props as any" @update:open="emit('update:open', $event)">
    <slot />
  </DrawerRoot>
</template>
