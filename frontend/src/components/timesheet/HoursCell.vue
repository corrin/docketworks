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
  commit: [raw: string, event: FocusEvent, reason: 'forward-tab' | null]
  keydown: [event: KeyboardEvent]
}>()

// Local string state so the user can freely type "1 1/4", "3/4", "1.5" etc.
// We only emit `commit` on blur; the parent parses and writes back to the row.
const local = ref<string>(props.hours > 0 ? formatHoursDisplay(props.hours) : '')
const blurReason = ref<'forward-tab' | null>(null)

watch(
  () => props.hours,
  (h) => {
    local.value = h > 0 ? formatHoursDisplay(h) : ''
  },
)

const isOvertime = () => props.hours > 8

function handleKeydown(event: KeyboardEvent): void {
  blurReason.value = event.key === 'Tab' && !event.shiftKey ? 'forward-tab' : null
  emit('keydown', event)
}

function handleBlur(event: FocusEvent): void {
  emit('commit', local.value, event, blurReason.value)
  blurReason.value = null
}
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
    @blur="handleBlur"
    @keydown="handleKeydown"
  />
</template>
