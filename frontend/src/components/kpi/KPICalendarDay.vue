<template>
  <div class="kpi-calendar-day" :class="dayClass" @click="$emit('click', dayData)">
    <div class="kpi-calendar-day__header">
      <div class="kpi-calendar-day__number">
        {{ dayData.day }}
      </div>
      <div v-if="dayData.holiday" class="kpi-calendar-day__holiday-tag">
        {{ dayData.holiday_name || 'Holiday' }}
      </div>
    </div>

    <div v-if="!dayData.holiday" class="kpi-calendar-day__content">
      <div class="kpi-calendar-day__row">
        <span class="kpi-calendar-day__value">{{ formatHours(dayData.billable_hours) }}</span>
        <span class="kpi-calendar-day__label">billable</span>
        <span class="kpi-calendar-day__sep">/</span>
        <span class="kpi-calendar-day__value">{{ formatHours(dayData.total_hours) }}</span>
        <span class="kpi-calendar-day__label">total</span>
      </div>

      <div class="kpi-calendar-day__row">
        <span class="kpi-calendar-day__value">{{
          formatCurrency(labourProfit, { decimals: 0 })
        }}</span>
        <span class="kpi-calendar-day__label">labour</span>
      </div>

      <div class="kpi-calendar-day__row">
        <span class="kpi-calendar-day__value">{{
          formatCurrency(materialsProfit, { decimals: 0 })
        }}</span>
        <span class="kpi-calendar-day__label">materials</span>
      </div>

      <div class="kpi-calendar-day__row">
        <span class="kpi-calendar-day__value">{{
          formatCurrency(adjustmentProfit, { decimals: 0 })
        }}</span>
        <span class="kpi-calendar-day__label">adjustments</span>
      </div>

      <div class="kpi-calendar-day__row kpi-calendar-day__gross-profit">
        <span class="kpi-calendar-day__value">{{
          formatCurrency(dayData.gross_profit, { decimals: 0 })
        }}</span>
        <span class="kpi-calendar-day__label">gross profit</span>
      </div>
    </div>

    <div v-else class="kpi-calendar-day__content">
      <div class="kpi-calendar-day__row kpi-calendar-day__gross-profit">
        <span class="kpi-calendar-day__value">{{
          formatCurrency(dayData.gross_profit, { decimals: 0 })
        }}</span>
        <span class="kpi-calendar-day__label">gross profit</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'
import { formatCurrency, formatHoursDisplay } from '@/utils/string-formatting'

type DayKPI = z.infer<typeof schemas.KPIDayData>
type Thresholds = z.infer<typeof schemas.KPIThresholds>

const props = defineProps<{
  dayData: DayKPI
  thresholds: Thresholds
}>()

defineEmits<{
  click: [dayData: DayKPI]
}>()

const dayClass = computed(() => {
  return {
    'kpi-calendar-day--green': props.dayData.color === 'green',
    'kpi-calendar-day--amber': props.dayData.color === 'amber',
    'kpi-calendar-day--red': props.dayData.color === 'red',
    'kpi-calendar-day--holiday': props.dayData.holiday,
    'kpi-calendar-day--clickable': true,
  }
})

const labourProfit = computed(() => {
  return props.dayData.details.time_revenue - props.dayData.details.staff_cost
})

const materialsProfit = computed(() => {
  return props.dayData.details.material_revenue - props.dayData.details.material_cost
})

const adjustmentProfit = computed(() => {
  return props.dayData.details.adjustment_revenue - props.dayData.details.adjustment_cost
})

function formatHours(hours: number): string {
  return formatHoursDisplay(hours)
}
</script>

<style scoped>
@reference 'tailwindcss';

.kpi-calendar-day {
  @apply min-h-[120px] p-2 border border-gray-200 bg-white relative;
  display: flex;
  flex-direction: column;
  font-size: 11px;
}

.kpi-calendar-day--clickable {
  @apply cursor-pointer transition-all duration-200 hover:shadow-md;
}

.kpi-calendar-day--green {
  @apply bg-green-50 border-green-200;
}

.kpi-calendar-day--amber {
  @apply bg-yellow-50 border-yellow-200;
}

.kpi-calendar-day--red {
  @apply bg-red-50 border-red-200;
}

.kpi-calendar-day--holiday {
  @apply bg-gray-50 border-gray-200;
}

.kpi-calendar-day__header {
  @apply flex items-baseline justify-between mb-1;
}

.kpi-calendar-day__number {
  @apply font-semibold text-gray-900;
  font-size: 13px;
}

.kpi-calendar-day__holiday-tag {
  @apply text-gray-400 font-medium;
  font-size: 10px;
}

.kpi-calendar-day__content {
  @apply flex-1 space-y-1;
}

.kpi-calendar-day__row {
  @apply flex items-baseline gap-1 flex-wrap;
}

.kpi-calendar-day__value {
  @apply font-medium text-gray-900;
}

.kpi-calendar-day__label {
  @apply text-gray-400;
  font-size: 10px;
}

.kpi-calendar-day__sep {
  @apply text-gray-300;
}

.kpi-calendar-day__gross-profit {
  @apply mt-0.5 pt-1 border-t border-gray-200;
}

.kpi-calendar-day__gross-profit .kpi-calendar-day__value {
  @apply font-semibold;
  font-size: 12px;
}

.kpi-calendar-day--green .kpi-calendar-day__number {
  @apply text-green-800;
}

.kpi-calendar-day--amber .kpi-calendar-day__number {
  @apply text-yellow-800;
}

.kpi-calendar-day--red .kpi-calendar-day__number {
  @apply text-red-800;
}

.kpi-calendar-day--green .kpi-calendar-day__value {
  @apply text-green-900;
}

.kpi-calendar-day--amber .kpi-calendar-day__value {
  @apply text-yellow-900;
}

.kpi-calendar-day--red .kpi-calendar-day__value {
  @apply text-red-900;
}
</style>
