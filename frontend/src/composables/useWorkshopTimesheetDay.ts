import { computed, ref, type Ref } from 'vue'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { toast } from 'vue-sonner'
import type { z } from 'zod'
import { toLocalDateString } from '@/utils/dateUtils'

type WorkshopTimesheetEntry = z.infer<typeof schemas.WorkshopTimesheetEntry>
type WorkshopTimesheetSummary = z.infer<typeof schemas.WorkshopTimesheetSummary>

type DailyData = Record<
  string,
  {
    entries: WorkshopTimesheetEntry[]
    summary: WorkshopTimesheetSummary | null
    loading?: boolean
  }
>

export type WorkingDayStartKey = 'mon_start' | 'tue_start' | 'wed_start' | 'thu_start' | 'fri_start'

export function formatDateKey(date: Date): string {
  return toLocalDateString(date)
}

export function parseDateKey(key: string): Date {
  return new Date(`${key}T00:00:00`)
}

export function formatFullDate(date: Date): string {
  return date.toLocaleDateString('en-AU', { weekday: 'long', month: 'short', day: 'numeric' })
}

export function useWorkshopTimesheetDay(selectedDate: Ref<string>) {
  const dailyData = ref<DailyData>({})

  const selectedEntries = computed(() => dailyData.value[selectedDate.value]?.entries ?? [])
  const selectedDaySummary = computed(() => {
    const day = dailyData.value[selectedDate.value]
    if (!day) return { jobs: 0, hours: 0 }
    return {
      jobs: new Set(day.entries.map((e) => e.job_id)).size,
      hours: day.summary?.total_hours ?? 0,
    }
  })
  const requiresLegacyFallback = computed(() =>
    selectedEntries.value.some((entry) => !entry.start_time || !entry.end_time),
  )
  const selectedJobIds = computed(() =>
    [
      ...new Set(
        selectedEntries.value
          .map((entry) => entry.job_id)
          .filter((id): id is string => typeof id === 'string' && Boolean(id)),
      ),
    ].sort(),
  )

  async function loadDay(dateKey: string, silent = false) {
    const existing = dailyData.value[dateKey] || { entries: [], summary: null }
    dailyData.value = {
      ...dailyData.value,
      [dateKey]: { ...existing, loading: true },
    }

    try {
      const response = await api.job_api_workshop_timesheets_retrieve({
        queries: { date: dateKey },
      })
      dailyData.value = {
        ...dailyData.value,
        [dateKey]: {
          entries: response.entries ?? [],
          summary: response.summary ?? null,
          loading: false,
        },
      }
    } catch (error) {
      console.error('Failed to load workshop timesheets', error)
      dailyData.value = {
        ...dailyData.value,
        [dateKey]: { ...existing, loading: false },
      }
      if (!silent) {
        toast.error('Failed to load timesheets for the day.')
      }
    }
  }

  return {
    dailyData,
    selectedEntries,
    selectedDaySummary,
    requiresLegacyFallback,
    selectedJobIds,
    loadDay,
  }
}
