import { reactive, ref, computed, type ComputedRef, type Ref } from 'vue'
import { api } from '@/api/client'
import axios from '@/plugins/axios'
import { schemas } from '@/api/generated/api'
import { toast } from 'vue-sonner'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import {
  calculateDurationHours,
  ensureTimeWithSeconds,
  formatTimeInputValue,
  minutesFromTime,
  minutesToTime,
  normalizeTimeRange,
} from '@/composables/useWorkshopTimesheetTimeUtils'
import type { z } from 'zod'

type WorkshopTimesheetEntry = z.infer<typeof schemas.WorkshopTimesheetEntry>
type WorkingDayStartKey = 'mon_start' | 'tue_start' | 'wed_start' | 'thu_start' | 'fri_start'

const DEFAULT_SLOT_MINUTES = 30
const WORKING_DAY_START_KEYS: Record<number, WorkingDayStartKey> = {
  1: 'mon_start',
  2: 'tue_start',
  3: 'wed_start',
  4: 'thu_start',
  5: 'fri_start',
}

export function useWorkshopTimesheetForm(options: {
  selectedDate: Ref<string>
  selectedEntries: ComputedRef<WorkshopTimesheetEntry[]>
  loadDay: (dateKey: string, silent?: boolean) => Promise<void>
  isDayLoading: Ref<boolean>
}) {
  const { selectedDate, selectedEntries, loadDay, isDayLoading } = options
  const isSubmitting = ref(false)
  const editingEntryId = ref<string | null>(null)
  const isFormOpen = ref(false)

  const formState = reactive({
    jobId: '',
    startTime: '',
    endTime: '',
    description: '',
    isBillable: true,
    rateMultiplier: 'Ord',
  })

  const companyDefaultsStore = useCompanyDefaultsStore()

  const formDurationHours = computed(() =>
    calculateDurationHours(formState.startTime, formState.endTime),
  )

  function getDefaultDayStartTime(dateKey = selectedDate.value): string {
    const fallback = '08:00'
    const defaults = companyDefaultsStore.companyDefaults
    if (!defaults) return fallback
    const dayIndex = new Date(`${dateKey}T00:00:00`).getDay()
    const startKey = WORKING_DAY_START_KEYS[dayIndex]
    if (!startKey) return fallback
    const startValue = defaults[startKey]
    return formatTimeInputValue(startValue) || fallback
  }

  function getLatestEntryEndTime(entries: WorkshopTimesheetEntry[]): string | null {
    const endMinutes = entries
      .map((entry) => formatTimeInputValue(entry.end_time))
      .filter((time): time is string => Boolean(time))
      .map((time) => minutesFromTime(time))
    if (endMinutes.length === 0) return null
    return minutesToTime(Math.max(...endMinutes))
  }

  function defaultTimeRange(startTime?: string) {
    const start = startTime || getDefaultDayStartTime()
    const end = minutesToTime(minutesFromTime(start) + DEFAULT_SLOT_MINUTES)
    return normalizeTimeRange(start, end, DEFAULT_SLOT_MINUTES)
  }

  function defaultNewEntryRange(range?: { start?: string; end?: string }) {
    const startValue =
      range?.start ?? getLatestEntryEndTime(selectedEntries.value) ?? getDefaultDayStartTime()
    const endValue = range?.end ?? minutesToTime(minutesFromTime(startValue) + DEFAULT_SLOT_MINUTES)
    return normalizeTimeRange(startValue, endValue, DEFAULT_SLOT_MINUTES)
  }

  function getLastUsedJobId(entries: WorkshopTimesheetEntry[]): string | null {
    for (let i = entries.length - 1; i >= 0; i -= 1) {
      const jobId = entries[i]?.job_id
      if (jobId) return jobId
    }
    return null
  }

  function rateLabelFromMultiplier(multiplier?: number | null): string {
    if (!multiplier || multiplier === 1) return 'Ord'
    const rounded = Math.round(multiplier * 10) / 10
    return Number.isInteger(rounded) ? `${rounded.toFixed(0)}.0` : rounded.toFixed(1)
  }

  function displayRate(multiplier?: number | null): string {
    const label = rateLabelFromMultiplier(multiplier)
    if (label.toLowerCase() === 'ord') return 'Ord'
    return `${label}x`
  }

  function multiplierValue(label: string): number {
    if (label.toLowerCase() === 'ord') return 1
    const parsed = Number(label)
    return Number.isFinite(parsed) ? parsed : 1
  }

  function safeRateMultiplier(value: unknown): number | null {
    return typeof value === 'number' ? value : null
  }

  function resetForm() {
    editingEntryId.value = null
    formState.jobId = ''
    formState.startTime = ''
    formState.endTime = ''
    formState.description = ''
    formState.isBillable = true
    formState.rateMultiplier = 'Ord'
  }

  function applyTimeRange(startTime: string, endTime: string) {
    const normalized = normalizeTimeRange(startTime, endTime, DEFAULT_SLOT_MINUTES)
    formState.startTime = normalized.start
    formState.endTime = normalized.end
  }

  function openCreateForm(range?: { start?: string; end?: string }) {
    resetForm()
    const lastJobId = getLastUsedJobId(selectedEntries.value)
    if (lastJobId) {
      formState.jobId = lastJobId
    }
    const defaults = defaultNewEntryRange(range)
    applyTimeRange(defaults.start, defaults.end)
    isFormOpen.value = true
  }

  function openEditForm(entry: WorkshopTimesheetEntry) {
    editingEntryId.value = entry.id
    formState.jobId = entry.job_id
    const fallbackRange = defaultTimeRange()
    const startValue = formatTimeInputValue(entry.start_time) || fallbackRange.start
    const fallbackMinutes = Math.max(entry.hours || 0.5, 0.25) * 60
    const computedEnd = minutesToTime(minutesFromTime(startValue) + Math.round(fallbackMinutes))
    applyTimeRange(
      formatTimeInputValue(entry.start_time) || fallbackRange.start,
      formatTimeInputValue(entry.end_time) || computedEnd,
    )
    formState.description = entry.description ?? ''
    formState.isBillable = entry.is_billable
    formState.rateMultiplier = rateLabelFromMultiplier(
      safeRateMultiplier(entry.wage_rate_multiplier),
    )
    isFormOpen.value = true
  }

  function setRangeToNow() {
    const now = new Date()
    const time = minutesToTime(now.getHours() * 60 + now.getMinutes())
    const defaultRange = defaultTimeRange(time)
    applyTimeRange(defaultRange.start, defaultRange.end)
  }

  function adjustRangeBy(minutesDelta: number) {
    if (!formState.startTime || !formState.endTime) return
    const normalized = normalizeTimeRange(
      formState.startTime,
      formState.endTime,
      DEFAULT_SLOT_MINUTES,
    )
    const start = minutesFromTime(normalized.start)
    let end = minutesFromTime(normalized.end) + minutesDelta
    if (end <= start) {
      end = Math.min(start + 1, 24 * 60 - 1)
    }
    applyTimeRange(normalized.start, minutesToTime(end))
  }

  function fillGapToNextEntry() {
    if (!formState.startTime) return
    const startMinutes = minutesFromTime(formState.startTime)
    const nextEntry = selectedEntries.value
      .filter((entry) => entry.start_time)
      .map((entry) => minutesFromTime(formatTimeInputValue(entry.start_time)))
      .filter((minutes) => minutes > startMinutes)
      .sort((a, b) => a - b)[0]

    if (typeof nextEntry === 'number') {
      applyTimeRange(formState.startTime, minutesToTime(nextEntry))
    } else {
      applyTimeRange(formState.startTime, '23:59')
    }
  }

  function resetToDefaultRange() {
    const defaults = defaultTimeRange()
    applyTimeRange(defaults.start, defaults.end)
  }

  async function submitForm() {
    if (!selectedDate.value) return
    if (!formState.startTime || !formState.endTime) {
      toast.error('Please choose a start and end time.')
      return
    }
    const hours = calculateDurationHours(formState.startTime, formState.endTime)
    if (!hours || hours < 0.01) {
      toast.error('Duration must be at least 1 minute.')
      return
    }
    if (!formState.jobId) {
      toast.error('Please select a job before saving.')
      return
    }

    const payload = {
      job_id: formState.jobId,
      accounting_date: selectedDate.value,
      start_time: ensureTimeWithSeconds(formState.startTime),
      end_time: ensureTimeWithSeconds(formState.endTime),
      hours,
      description: formState.description || '',
      is_billable: formState.isBillable,
      rate_multiplier: multiplierValue(formState.rateMultiplier),
    }

    try {
      isSubmitting.value = true
      isDayLoading.value = true
      if (editingEntryId.value) {
        await api.job_api_workshop_timesheets_partial_update({
          entry_id: editingEntryId.value,
          ...payload,
        })
      } else {
        await api.job_api_workshop_timesheets_create(payload)
      }
      toast.success('Time saved.')
      resetForm()
      isFormOpen.value = false
      await loadDay(selectedDate.value)
    } catch (error) {
      console.error('Failed to save workshop timesheet entry', error)
      toast.error('Failed to save entry.')
    } finally {
      isSubmitting.value = false
      isDayLoading.value = false
    }
  }

  async function handleDeleteEntry(id: string): Promise<void> {
    if (!id) return
    try {
      isDayLoading.value = true
      await axios.delete('/job/api/workshop/timesheets/', { data: { entry_id: id } })
      toast.success('Entry deleted.')
      await loadDay(selectedDate.value)
    } catch (error) {
      console.error('Failed to delete workshop timesheet entry', error)
      toast.error('Failed to delete entry.')
    } finally {
      isDayLoading.value = false
    }
  }

  async function deleteEntryFromDrawer() {
    if (!editingEntryId.value) return
    await handleDeleteEntry(editingEntryId.value)
    resetForm()
    isFormOpen.value = false
  }

  return {
    formState,
    editingEntryId,
    isFormOpen,
    isSubmitting,
    formDurationHours,
    openCreateForm,
    openEditForm,
    submitForm,
    handleDeleteEntry,
    deleteEntryFromDrawer,
    resetForm,
    setRangeToNow,
    adjustRangeBy,
    fillGapToNextEntry,
    resetToDefaultRange,
    displayRate,
    safeRateMultiplier,
    formatTimeInputValue,
  }
}
