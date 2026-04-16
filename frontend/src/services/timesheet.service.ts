import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '../utils/debug'
import { toLocalDateString } from '../utils/dateUtils'
import { formatHoursDisplay } from '@/utils/string-formatting'
import type { z } from 'zod'

type Staff = z.infer<typeof schemas.ModernStaff>
type Job = z.infer<typeof schemas.ModernTimesheetJob>
type WeeklyOverviewData = z.infer<typeof schemas.WeeklyTimesheetData>
type CostLine = z.infer<typeof schemas.CostLine>

export class TimesheetService {
  static async getStaff(): Promise<Staff[]> {
    try {
      const staffResponse = await api.timesheets_staff_retrieve()
      const staffList = staffResponse.staff ?? []

      const defaults = await api.company_defaults_retrieve()
      const defaultWageRate = defaults.wage_rate ?? 0

      const normalizedStaff = staffList.map((staff) => ({
        ...staff,
        wageRate: staff.wageRate ?? defaultWageRate,
      }))

      debugLog('Staff normalized for timesheet:', {
        count: normalizedStaff.length,
        sample: normalizedStaff[0],
        defaultWageRate,
        keys: normalizedStaff[0] ? Object.keys(normalizedStaff[0]) : [],
      })

      return normalizedStaff
    } catch (error) {
      debugLog('Error fetching staff:', error)
      throw error
    }
  }

  // Legacy method - use CostLine queries instead
  static async getTimeEntries(staffId: string, date: string): Promise<CostLine[]> {
    try {
      const response = await api.job_timesheet_entries_retrieve({
        queries: { staff_id: staffId, date },
      })
      const parsed = schemas.ModernTimesheetEntryGetResponse.parse(response)
      return parsed.cost_lines || []
    } catch (error) {
      debugLog('Error fetching cost lines:', error)
      throw error
    }
  }

  static async getJobs(): Promise<Job[]> {
    try {
      const jobsResponse = await api.timesheets_jobs_retrieve()
      return jobsResponse.jobs || []
    } catch (error) {
      debugLog('Error fetching jobs:', error)
      throw error
    }
  }

  static async getWeeklyOverview(startDate: string): Promise<WeeklyOverviewData> {
    try {
      const response = await api.timesheets_weekly_retrieve({
        queries: { start_date: startDate },
      })
      return schemas.WeeklyTimesheetData.parse(response)
    } catch (error) {
      debugLog('Error fetching weekly overview:', error)
      throw error
    }
  }

  static getCurrentWeekRange(): { startDate: string; endDate: string } {
    const today = new Date()
    const monday = new Date(today)
    monday.setDate(today.getDate() - today.getDay() + 1)

    const sunday = new Date(monday)
    sunday.setDate(monday.getDate() + 6)

    return {
      startDate: toLocalDateString(monday),
      endDate: toLocalDateString(sunday),
    }
  }

  static formatDate(date: string): string {
    return new Date(date).toLocaleDateString('en-NZ', {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  static formatHours(hours: number): string {
    return formatHoursDisplay(hours)
  }

  static async getStaffList(): Promise<Staff[]> {
    return this.getStaff()
  }

  static async getAvailableJobs(): Promise<Job[]> {
    return this.getJobs()
  }
}
