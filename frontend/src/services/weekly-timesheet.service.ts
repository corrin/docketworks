// src/services/weekly-timesheet.service.ts

import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import { dateService } from '@/services/date.service'
import { formatHoursDisplay } from '@/utils/string-formatting'

type WeeklyTimesheetData = z.infer<typeof schemas.WeeklyTimesheetData>

/**
 * Fetch weekly timesheet overview.
 * Includes all payroll breakdown data (billed/unbilled/overtime/leave).
 */
export async function fetchWeeklyOverview(startDate?: string): Promise<WeeklyTimesheetData> {
  const queries: Record<string, string> = {}
  if (startDate) {
    queries.start_date = startDate
  }
  const response = await api.timesheets_api_weekly_retrieve({ queries })
  return response
}

/**
 * Get the current week’s start/end dates.
 */
export function getCurrentWeekRange(): { startDate: string; endDate: string } {
  const { startDate, endDate } = dateService.getCurrentWeekRange()
  return { startDate, endDate }
}

/**
 * Get the week’s start/end dates for an arbitrary date.
 */
export function getWeekRange(date: Date): { startDate: string; endDate: string } {
  const { startDate, endDate } = dateService.getWeekRange(date)
  return { startDate, endDate }
}

/**
 * Format a date range as a human-readable string.
 */
export function formatDateRange(startDate: string, endDate: string): string {
  return dateService.formatDateRange(startDate, endDate)
}

/**
 * Format hours with one decimal.
 * API always returns numeric values.
 */
export function formatHours(hours: number): string {
  // Handle invalid values
  if (isNaN(hours)) {
    console.warn('formatHours received invalid value:', hours)
    return '0'
  }

  return formatHoursDisplay(hours)
}

/**
 * Format a percentage with one decimal.
 * API always returns numeric values.
 */
export function formatPercentage(percentage: number): string {
  // Handle invalid values
  if (isNaN(percentage)) {
    console.warn('formatPercentage received invalid value:', percentage)
    return '0.0%'
  }

  return `${percentage.toFixed(1)}%`
}

export default {
  fetchWeeklyOverview,
  getCurrentWeekRange,
  getWeekRange,
  formatDateRange,
  formatHours,
  formatPercentage,
}
