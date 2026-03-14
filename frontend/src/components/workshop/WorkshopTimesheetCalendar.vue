<script setup lang="ts">
import CalendarView from '@kodeglot/vue-calendar'
import type { ComponentPublicInstance } from 'vue'

type CalendarViewInstance = (ComponentPublicInstance & { $refs?: Record<string, unknown> }) | null

interface Props {
  initialDate: Date
  onCalendarReady: (instance: CalendarViewInstance | null) => void
  onOpenEventModal: (date?: Date | string | null) => void
  onEventClick: (event: { id?: string; metadata?: Record<string, unknown> } | null) => void
  onDateChange: (newDate: Date) => void
}

defineProps<Props>()
</script>

<template>
  <CalendarView
    :ref="(instance: CalendarViewInstance | null) => onCalendarReady(instance)"
    class="workshop-calendar w-full rounded-xl border bg-white shadow-sm"
    data-automation-id="WorkshopTimesheetCalendar"
    height="auto"
    :initial-date="initialDate"
    initial-view="day"
    time-format="24h"
    :show-controls="false"
    :show-event-button="false"
    :show-demo-events="false"
    :enable-drag-drop="false"
    @open-event-modal="onOpenEventModal"
    @event-click="onEventClick"
    @date-change="onDateChange"
  >
    <template #event-modal />
  </CalendarView>
</template>
