<script setup lang="ts">
import { ref, watch } from 'vue'
import { Input } from '../ui/input'
import { formatHoursDisplay } from '@/utils/string-formatting'

const props = withDefaults(
  defineProps<{
    hours: number
    disabled?: boolean
    automationId?: string
  }>(),
  { disabled: false, automationId: 'HoursCell-input' },
)

const emit = defineEmits<{
  commit: [raw: string]
  keydown: [event: KeyboardEvent]
}>()

// Local string state so the user can freely type "1 1/4", "3/4", "1.5" etc.
// We only emit `commit` on blur; the parent parses and writes back to the row.
const local = ref<string>(props.hours > 0 ? formatHoursDisplay(props.hours) : '')

watch(
  () => props.hours,
  (h) => {
    local.value = h > 0 ? formatHoursDisplay(h) : ''
  },
)

const isOvertime = () => props.hours > 8
</script>

<template>
  <Input
    v-model="local"
    :disabled="disabled"
    type="text"
    inputmode="decimal"
    class="text-right text-sm numeric-input w-16"
    :class="isOvertime() ? 'text-red-600 font-semibold' : 'text-slate-700'"
    :data-automation-id="automationId"
    @blur="emit('commit', local)"
    @keydown="emit('keydown', $event)"
  />
</template>
