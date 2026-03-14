<script setup lang="ts">
import { reactive, watch } from 'vue'
import Input from '@/components/ui/input/Input.vue'
import type { DateRange } from '@/constants/date-range'

const props = defineProps<{ modelValue: DateRange }>()
const emit = defineEmits(['update:modelValue'])

const range = reactive<DateRange>({
  from: props.modelValue?.from || undefined,
  to: props.modelValue?.to || undefined,
})

watch(
  () => props.modelValue,
  (val) => {
    range.from = val?.from || undefined
    range.to = val?.to || undefined
  },
  { deep: true },
)

watch(
  () => ({ ...range }),
  (val) => emit('update:modelValue', val),
  { deep: true },
)
</script>

<template>
  <div class="flex items-center gap-2">
    <Input type="date" v-model="range.from" class="w-36" />
    <span class="mx-1">–</span>
    <Input type="date" v-model="range.to" class="w-36" />
  </div>
</template>
