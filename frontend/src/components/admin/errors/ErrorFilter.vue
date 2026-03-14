<script setup lang="ts">
import Input from '@/components/ui/input/Input.vue'
import { CustomDatePicker } from '@/components/ui/custom-date-picker'
import { useVModel } from '@vueuse/core'
import { type FilterState } from '@/constants/date-range'

const props = defineProps<{ modelValue: FilterState }>()
const emit = defineEmits<{ 'update:modelValue': [FilterState] }>()

const model = useVModel(props, 'modelValue', emit)
</script>

<template>
  <div class="flex flex-col md:flex-row items-end gap-4">
    <Input v-model="model.search" placeholder="Search…" class="md:w-64" />
    <CustomDatePicker v-model="model.range" />
  </div>
</template>
