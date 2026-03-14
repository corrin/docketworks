<template>
  <div class="kpi-calendar">
    <div class="kpi-calendar__header">
      <h3 class="kpi-calendar__title">{{ monthYear }}</h3>
    </div>

    <div class="kpi-calendar__grid">
      <!-- Day headers -->
      <div class="kpi-calendar__day-headers">
        <div v-for="day in dayHeaders" :key="day" class="kpi-calendar__day-header">
          {{ day }}
        </div>
      </div>

      <!-- Calendar days -->
      <div class="kpi-calendar__days">
        <!-- Previous month padding -->
        <div v-for="n in paddingDays" :key="`padding-${n}`" class="kpi-calendar__day-empty" />

        <!-- Current month days -->
        <KPICalendarDay
          v-for="day in calendarDays"
          :key="day.date"
          :day-data="day"
          :thresholds="thresholds"
          @click="$emit('dayClick', day)"
        />

        <!-- Next month padding -->
        <div v-for="n in remainingDays" :key="`remaining-${n}`" class="kpi-calendar__day-empty" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'
import KPICalendarDay from './KPICalendarDay.vue'

type DayKPI = z.infer<typeof schemas.KPIDayData>
type Thresholds = z.infer<typeof schemas.KPIThresholds>

const props = defineProps<{
  calendarData: Record<string, DayKPI>
  thresholds: Thresholds
  year: number
  month: number
}>()

defineEmits<{
  dayClick: [day: DayKPI]
}>()

const dayHeaders = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

const monthYear = computed(() => {
  const date = new Date(props.year, props.month - 1)
  return date.toLocaleDateString('en-NZ', {
    month: 'long',
    year: 'numeric',
  })
})

const calendarDays = computed(() => {
  return Object.values(props.calendarData).sort((a, b) => {
    return new Date(a.date).getTime() - new Date(b.date).getTime()
  })
})

const paddingDays = computed(() => {
  const firstDay = new Date(props.year, props.month - 1, 1)
  const dayOfWeek = firstDay.getDay()

  // Convert to Monday-based (0 = Mon, 6 = Sun)
  // Skip weekends entirely
  if (dayOfWeek === 0 || dayOfWeek === 6) return 0
  return dayOfWeek - 1
})

const remainingDays = computed(() => {
  const totalCells = 35 // 5 days × 7 weeks max
  const usedCells = paddingDays.value + calendarDays.value.length
  return totalCells - usedCells
})
</script>

<style scoped>
@reference 'tailwindcss';

.kpi-calendar {
  @apply bg-white rounded-lg border border-gray-200 shadow-sm;
}

.kpi-calendar__header {
  @apply p-4 border-b border-gray-200;
}

.kpi-calendar__title {
  @apply text-lg font-semibold text-gray-900;
}

.kpi-calendar__grid {
  @apply p-4;
}

.kpi-calendar__day-headers {
  @apply grid grid-cols-5 gap-1 mb-1;
}

.kpi-calendar__day-header {
  @apply text-center font-medium text-gray-500 py-2;
  font-size: 12px;
}

.kpi-calendar__days {
  @apply grid grid-cols-5 gap-1;
}

.kpi-calendar__day-empty {
  @apply min-h-[120px] bg-gray-50 border border-gray-100;
}

@media (max-width: 768px) {
  .kpi-calendar__days {
    @apply grid-cols-1 gap-2;
  }

  .kpi-calendar__day-headers {
    @apply grid-cols-1;
  }

  .kpi-calendar__day-header {
    @apply text-left;
  }

  .kpi-calendar__day-empty {
    @apply hidden;
  }
}
</style>
