<script setup lang="ts">
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useVModel } from '@vueuse/core'

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits(['update:modelValue'])
const model = useVModel(props, 'modelValue', emit)
</script>

<template>
  <Tabs v-model="model">
    <TabsList class="w-full">
      <TabsTrigger value="xero">Xero Errors</TabsTrigger>
      <TabsTrigger value="system">System Errors</TabsTrigger>
      <TabsTrigger value="job">Job Errors</TabsTrigger>
    </TabsList>
  </Tabs>
</template>
