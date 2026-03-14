<template>
  <div class="flex items-center space-x-2">
    <Select
      :model-value="selectedValue"
      @update:model-value="(v) => handleMonthChange(v as string)"
    >
      <SelectTrigger
        class="h-8 w-auto min-w-[120px] text-xs bg-slate-800/50 border-blue-500/30 text-white hover:bg-slate-800/70"
      >
        <SelectValue :placeholder="displayValue" />
      </SelectTrigger>
      <SelectContent class="bg-slate-800 border-blue-500/30 max-h-60 overflow-y-auto">
        <SelectItem
          v-for="option in monthOptions"
          :key="option.value"
          :value="option.value"
          class="text-white hover:bg-blue-500/20 focus:bg-blue-500/30"
        >
          {{ option.label }}
        </SelectItem>
      </SelectContent>
    </Select>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const props = defineProps<{
  year: number
  month: number
}>()

const emit = defineEmits<{
  'update:year': [value: number]
  'update:month': [value: number]
}>()

const selectedValue = computed(() => `${props.year}-${props.month.toString().padStart(2, '0')}`)

const displayValue = computed(() => {
  const monthNames = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ]
  return `${monthNames[props.month - 1]} ${props.year}`
})

const monthOptions = computed(() => {
  const options = []
  const currentYear = new Date().getFullYear()
  const currentMonth = new Date().getMonth() + 1

  for (let year = currentYear; year >= currentYear - 2; year--) {
    for (let month = 12; month >= 1; month--) {
      if (year === currentYear && month > currentMonth) {
        continue
      }

      const monthNames = [
        'January',
        'February',
        'March',
        'April',
        'May',
        'June',
        'July',
        'August',
        'September',
        'October',
        'November',
        'December',
      ]

      const value = `${year}-${month.toString().padStart(2, '0')}`
      const label = `${monthNames[month - 1]} ${year}`

      options.push({ value, label })
    }
  }

  return options
})

function handleMonthChange(value: string) {
  const [year, month] = value.split('-')
  emit('update:year', parseInt(year))
  emit('update:month', parseInt(month))
}
</script>
