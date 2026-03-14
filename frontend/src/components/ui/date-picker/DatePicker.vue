<script setup lang="ts">
import { DateFormatter, getLocalTimeZone, parseDate, type DateValue } from '@internationalized/date'
import { ref, watch, computed } from 'vue'
import { CalendarIcon } from 'lucide-vue-next'

import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

const props = withDefaults(
  defineProps<{
    modelValue: string | null
    min?: string | null
    max?: string | null
    placeholder?: string
    label?: string
    class?: string
  }>(),
  { modelValue: null },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: string | null): void
}>()

const tz = getLocalTimeZone()
const df = new DateFormatter('en-NZ', { dateStyle: 'long' })

const internal = ref<DateValue>()

watch(
  () => props.modelValue,
  (v) => {
    internal.value = v ? parseDate(v) : undefined
  },
  { immediate: true },
)

function select(date?: DateValue) {
  internal.value = date
  emit('update:modelValue', date ? date.toDate(tz).toISOString().slice(0, 10) : null)
}

const minValue = computed(() => (props.min ? parseDate(props.min) : undefined))
const maxValue = computed(() => (props.max ? parseDate(props.max) : undefined))

const text = computed(() =>
  internal.value ? df.format(internal.value.toDate(tz)) : (props.placeholder ?? 'Pick a date'),
)
</script>

<template>
  <div class="flex flex-col gap-1" :class="props.class">
    <label v-if="props.label" class="text-sm font-medium">{{ props.label }}</label>

    <Popover>
      <PopoverTrigger as-child>
        <Button variant="outline" class="justify-start font-normal w-full">
          <CalendarIcon class="mr-2 h-4 w-4" />
          {{ text }}
        </Button>
      </PopoverTrigger>

      <PopoverContent class="w-auto p-0">
        <Calendar
          v-model="internal"
          :min-value="minValue"
          :max-value="maxValue"
          initial-focus
          @update:modelValue="select"
        />
      </PopoverContent>
    </Popover>
  </div>
</template>
