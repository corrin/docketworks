import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { debugLog } from '@/utils/debug'
import { toLocalDateString } from '@/utils/dateUtils'
import { formatCurrency, formatHoursDisplay } from '@/utils/string-formatting'
import type { z } from 'zod'

// Types for params - keeping as local since they're for input validation
export interface KPICalendarParams {
  start_date: string
}

export interface KPIAccountingParams {
  year?: number
  month?: number
}

// Type aliases for generated types (for backward compatibility)
export type KPIDay = z.infer<typeof schemas.KPIDayData>
export type DayKPI = KPIDay
export type DayDetails = z.infer<typeof schemas.KPIDetails>
export type JobBreakdown = z.infer<typeof schemas.KPIJobBreakdown>
export type MonthlyTotals = z.infer<typeof schemas.KPIMonthlyTotals>
export type Thresholds = z.infer<typeof schemas.KPIThresholds>
export type KPICalendarResponse = z.infer<typeof schemas.KPICalendarData>
export type KPICalendarData = KPICalendarResponse

class KPIService {
  async getKPICalendarData(params: KPICalendarParams): Promise<KPICalendarData> {
    try {
      // Use the generated API
      const lookupDate = new Date(params.start_date)
      return await api.accounting_reports_calendar_retrieve({
        queries: {
          month: lookupDate.getMonth() + 1,
          year: lookupDate.getFullYear(),
        },
      })
    } catch (error) {
      debugLog('Error fetching KPI calendar data:', error)
      throw error
    }
  }

  async getAccountingKPICalendarData(
    params: KPIAccountingParams = {},
  ): Promise<KPICalendarResponse> {
    try {
      debugLog('Fetching KPI data with params:', params)

      // Use the generated Zodios client with query parameters
      const response = await api.accounting_reports_calendar_retrieve({
        queries: {
          year: params.year,
          month: params.month,
        },
      })

      debugLog('KPI data fetched successfully:', {
        year: response.year,
        month: response.month,
        daysCount: Object.keys(response.calendar_data).length,
      })

      return response
    } catch (error) {
      debugLog('Error fetching accounting KPI calendar data:', error)
      throw error
    }
  }

  formatDateForAPI(date: Date): string {
    return toLocalDateString(date)
  }

  formatCurrency(value: number): string {
    return formatCurrency(value)
  }

  formatHours(hours: number): string {
    return formatHoursDisplay(hours)
  }

  formatPercentage(value: number): string {
    return `${Math.round(value)}%`
  }

  getPerformanceRating(daysGreen: number, daysAmber: number, daysRed: number): string {
    const totalDays = daysGreen + daysAmber + daysRed
    if (totalDays === 0) return '0'
    const greenPercentage = (daysGreen / totalDays) * 100
    return `${Math.round(greenPercentage)}`
  }

  getMonthName(month: number): string {
    const months = [
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
    return months[month - 1] || 'Unknown'
  }

  getWeekStart(date: Date): Date {
    const weekStart = new Date(date)
    const day = weekStart.getDay()
    const diff = weekStart.getDate() - day + (day === 0 ? -6 : 1)
    weekStart.setDate(diff)
    return weekStart
  }

  getWeekDays(startDate: Date): Date[] {
    const days: Date[] = []
    for (let i = 0; i < 5; i++) {
      const day = new Date(startDate)
      day.setDate(startDate.getDate() + i)
      days.push(day)
    }
    return days
  }
}

export const kpiService = new KPIService()
export default kpiService
