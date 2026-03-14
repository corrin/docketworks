import { schemas } from '../api/generated/api'
import { api } from '../api/client'
import { today } from './date.service'
import type { z } from 'zod'
import { formatCurrency as formatCurrencyUtil, formatHoursDisplay } from '@/utils/string-formatting'

// Use inferred types from Zod schemas
export type DailyTimesheetSummary = z.infer<typeof schemas.DailyTimesheetSummary>
export type StaffDailyData = z.infer<typeof schemas.StaffDailyData>

// All interfaces migrated to generated types from ../api/generated/api
// - JobBreakdown (now from generated API)
// - StaffDailyData (now from generated API)
// - DailyTotals (now from generated API)
// - SummaryStats (now from generated API)
// - DailyTimesheetSummary (now from generated API)

export const getDailyTimesheetSummary = async (date?: string): Promise<DailyTimesheetSummary> => {
  // Date is now required in the API path - use today() if not provided
  const targetDate = date || today()
  return await api.getDailyTimesheetSummaryByDate({
    params: { target_date: targetDate },
  })
}

export const getStaffDailyDetail = async (
  staffId: string,
  date?: string,
): Promise<StaffDailyData> => {
  // Date is now required in the API path - use today() if not provided
  const targetDate = date || today()
  // Backend returns single StaffDailyData object, not full DailyTimesheetSummary
  const response = (await api.getStaffDailyTimesheetDetailByDate({
    params: {
      staff_id: staffId,
      target_date: targetDate,
    },
  })) as unknown as StaffDailyData
  return response
}

export const formatHours = (hours: number): string => {
  return formatHoursDisplay(hours)
}

export const formatCurrency = (amount: number): string => {
  return formatCurrencyUtil(amount)
}

export const getStatusVariant = (statusClass: string): string => {
  const variants: Record<string, string> = {
    success: 'success',
    warning: 'warning',
    danger: 'destructive',
    secondary: 'secondary',
  }
  return variants[statusClass] || 'secondary'
}

export default {
  getDailyTimesheetSummary,
  getStaffDailyDetail,
  formatHours,
  formatCurrency,
  getStatusVariant,
}
