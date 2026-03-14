import { computed, nextTick, onBeforeUnmount, ref, watch, type ComputedRef, type Ref } from 'vue'
import { useCalendarStore, type CalendarEvent } from '@kodeglot/vue-calendar'
import dayjs from 'dayjs'
import { schemas } from '@/api/generated/api'
import {
  combineDateTime,
  calculateDurationHours,
  formatHoursValue,
  formatTimeInputValue,
} from '@/composables/useWorkshopTimesheetTimeUtils'
import { formatDateKey } from '@/composables/useWorkshopTimesheetDay'
import { formatHoursDisplay } from '@/utils/string-formatting'
import type { ComponentPublicInstance } from 'vue'
import type { z } from 'zod'
import type { JobBudgetMeta } from '@/composables/useWorkshopJobBudgets'

type WorkshopTimesheetEntry = z.infer<typeof schemas.WorkshopTimesheetEntry>

type CalendarViewEventModalRef = {
  openModal?: (date: Date) => void
  openEditModal?: (event: Record<string, unknown>) => void
  closeModal?: () => void
  __workshopSuppressed?: boolean
  [key: string]: unknown
}
type CalendarViewInstance = (ComponentPublicInstance & { $refs?: Record<string, unknown> }) | null

export function useWorkshopCalendarSync(options: {
  selectedDate: Ref<string>
  selectedEntries: ComputedRef<WorkshopTimesheetEntry[]>
  requiresLegacyFallback: ComputedRef<boolean>
  getJobBudgetState: (jobId?: string | null) => JobBudgetMeta | null
  onCreateEntry: (range?: { start?: string; end?: string }) => void
  onEditEntry: (entry: WorkshopTimesheetEntry) => void
  onSelectDay: (dateKey: string) => void
}) {
  const {
    selectedDate,
    selectedEntries,
    requiresLegacyFallback,
    getJobBudgetState,
    onCreateEntry,
    onEditEntry,
    onSelectDay,
  } = options

  const calendarStore = useCalendarStore()
  const trackedCalendarEventIds = ref<Set<string>>(new Set())
  const calendarViewRef = ref<CalendarViewInstance>(null)
  let calendarModalSuppressionFrame: number | null = null

  const calendarEventPayloads = computed<CalendarEvent[]>(() =>
    selectedEntries.value
      .filter((entry) => entry.start_time && entry.end_time)
      .map((entry) => toCalendarEvent(entry)),
  )

  const calendarEventTooltipMap = computed(() => {
    const map = new Map<string, string>()
    calendarEventPayloads.value.forEach((event) => {
      const metadata = (event as { metadata?: Record<string, unknown> }).metadata || {}
      const tooltipFromMetadata =
        typeof metadata.budgetTooltip === 'string' ? (metadata.budgetTooltip as string) : null
      const tooltipFromEvent =
        typeof (event as Record<string, unknown>).tooltip === 'string'
          ? ((event as Record<string, unknown>).tooltip as string)
          : null
      const tooltip = tooltipFromMetadata || tooltipFromEvent
      if (tooltip) {
        map.set(String(event.id), tooltip)
      }
    })
    return map
  })

  function formatEventTitle(entry: WorkshopTimesheetEntry): string {
    const jobNumber = entry.job_number ? `#${entry.job_number}` : ''
    const jobName = entry.job_name || 'Job'
    const duration =
      calculateDurationHours(
        formatTimeInputValue(entry.start_time),
        formatTimeInputValue(entry.end_time),
      ) ||
      entry.hours ||
      0
    const durationLabel = duration ? formatHoursDisplay(duration) : ''
    return [jobNumber, jobName, durationLabel ? `(${durationLabel})` : ''].filter(Boolean).join(' ')
  }

  function toCalendarEvent(entry: WorkshopTimesheetEntry): CalendarEvent {
    const dateKey = entry.accounting_date || selectedDate.value
    const startIso = combineDateTime(dateKey, entry.start_time ?? '00:00').toISOString()
    const endIso = combineDateTime(dateKey, entry.end_time ?? '00:00').toISOString()
    const budgetMeta = getJobBudgetState(entry.job_id)
    const overBudget = budgetMeta?.overBudget ?? false
    const budgetTooltip =
      budgetMeta && budgetMeta.overBudget
        ? `Over estimate: ${formatHoursValue(budgetMeta.actualHours)} / ${formatHoursValue(budgetMeta.estimatedHours)}`
        : ''
    return {
      id: entry.id,
      title: formatEventTitle(entry),
      start: startIso,
      end: endIso,
      tailwindColor: overBudget ? 'red' : 'sky',
      metadata: {
        entryId: entry.id,
        jobId: entry.job_id,
        overBudget,
        budgetTooltip: budgetTooltip || undefined,
        estimatedHours: budgetMeta?.estimatedHours,
        actualHours: budgetMeta?.actualHours,
      },
      ...(budgetTooltip ? { tooltip: budgetTooltip } : {}),
    }
  }

  function clearCalendarEvents() {
    trackedCalendarEventIds.value.forEach((id) => {
      calendarStore.deleteEvent(id)
    })
    trackedCalendarEventIds.value = new Set<string>()
  }

  function applyEventTooltips() {
    if (typeof document === 'undefined') return
    void nextTick(() => {
      const tooltipMap = calendarEventTooltipMap.value
      trackedCalendarEventIds.value.forEach((id) => {
        const element = document.querySelector(`[data-event-id="${id}"]`)
        if (!(element instanceof HTMLElement)) return
        const tooltip = tooltipMap.get(String(id))
        if (tooltip) {
          element.setAttribute('title', tooltip)
          element.setAttribute('aria-label', `Calendar event (${tooltip})`)
        } else {
          element.removeAttribute('title')
          element.setAttribute('aria-label', 'Calendar event')
        }
      })
    })
  }

  function syncCalendarStoreEvents() {
    if (requiresLegacyFallback.value) {
      clearCalendarEvents()
      return
    }
    const desiredEvents = calendarEventPayloads.value
    const desiredIds = new Set<string>(desiredEvents.map((event) => String(event.id)))
    trackedCalendarEventIds.value.forEach((id) => {
      if (!desiredIds.has(id)) {
        calendarStore.deleteEvent(id)
      }
    })
    desiredEvents.forEach((event) => {
      const eventId = String(event.id)
      const normalizedEvent = { ...event, id: eventId }
      if (trackedCalendarEventIds.value.has(eventId)) {
        calendarStore.updateEvent(normalizedEvent)
      } else {
        calendarStore.addEvent(normalizedEvent)
      }
    })
    trackedCalendarEventIds.value = desiredIds
    applyEventTooltips()
  }

  function handleCalendarOpenEventModal(date?: Date | string | null) {
    if (!date) {
      onCreateEntry()
      return
    }
    const candidate = dayjs(date)
    if (!candidate.isValid()) {
      onCreateEntry()
      return
    }
    onCreateEntry({
      start: candidate.format('HH:mm'),
    })
  }

  function handleCalendarEventClick(
    event: { id?: string; metadata?: Record<string, unknown> } | null,
  ) {
    if (!event) return
    const entryId =
      (event.metadata?.entryId as string | undefined) ??
      (typeof event.id === 'string' ? event.id : undefined)
    if (!entryId) return
    const entry = selectedEntries.value.find((item) => item.id === entryId)
    if (entry) {
      onEditEntry(entry)
    }
  }

  function handleCalendarDateChange(newDate: Date) {
    if (!(newDate instanceof Date) || Number.isNaN(newDate.getTime())) return
    const dateKey = formatDateKey(newDate)
    if (selectedDate.value !== dateKey) {
      onSelectDay(dateKey)
    }
  }

  function getCalendarEventModal(): CalendarViewEventModalRef | null {
    const instance = calendarViewRef.value
    if (!instance) return null
    const publicRefs = instance.$refs as Record<string, unknown> | undefined
    const internalRefs = (instance as { $?: { refs?: Record<string, unknown> } }).$?.refs
    const instanceRecord = instance as unknown as Record<string, unknown>
    const modal =
      (publicRefs?.eventModal as CalendarViewEventModalRef | undefined) ??
      (internalRefs?.eventModal as CalendarViewEventModalRef | undefined) ??
      (instanceRecord.eventModal as CalendarViewEventModalRef | undefined)
    return modal ?? null
  }

  function suppressVendorCalendarModal(): boolean {
    const modal = getCalendarEventModal()
    if (!modal) return false
    if (modal.__workshopSuppressed) return true
    modal.openModal = () => {}
    modal.openEditModal = () => {}
    modal.closeModal = modal.closeModal ?? (() => {})
    modal.__workshopSuppressed = true
    return true
  }

  function cancelModalSuppressionLoop() {
    if (typeof window === 'undefined') return
    if (calendarModalSuppressionFrame !== null) {
      window.cancelAnimationFrame(calendarModalSuppressionFrame)
      calendarModalSuppressionFrame = null
    }
  }

  function scheduleModalSuppression() {
    if (typeof window === 'undefined' || requiresLegacyFallback.value) return
    if (suppressVendorCalendarModal()) {
      cancelModalSuppressionLoop()
      return
    }
    if (calendarModalSuppressionFrame !== null) return
    const attempt = () => {
      if (suppressVendorCalendarModal()) {
        cancelModalSuppressionLoop()
        return
      }
      calendarModalSuppressionFrame = window.requestAnimationFrame(attempt)
    }
    calendarModalSuppressionFrame = window.requestAnimationFrame(attempt)
  }

  watch(
    calendarEventPayloads,
    () => {
      syncCalendarStoreEvents()
    },
    { immediate: true },
  )

  watch(
    requiresLegacyFallback,
    (fallbackActive) => {
      syncCalendarStoreEvents()
      if (fallbackActive) {
        cancelModalSuppressionLoop()
      } else {
        scheduleModalSuppression()
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    clearCalendarEvents()
    cancelModalSuppressionLoop()
  })

  return {
    calendarStore,
    calendarViewRef,
    syncCalendarStoreEvents,
    handleCalendarOpenEventModal,
    handleCalendarEventClick,
    handleCalendarDateChange,
    scheduleModalSuppression,
    cancelModalSuppressionLoop,
  }
}
