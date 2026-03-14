import api from '@/plugins/axios'
import { debugLog } from '@/utils/debug'
import {
  formatCurrency,
  formatHoursDisplay,
  toCsvString,
  downloadCsv,
} from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'
import type {
  StaffPerformanceReportResponse,
  StaffPerformanceReportParams,
  StaffPerformanceData,
  TeamAverages,
} from '@/types/staff-performance.types'

export class StaffPerformanceReportService {
  private static instance: StaffPerformanceReportService

  static getInstance(): StaffPerformanceReportService {
    if (!StaffPerformanceReportService.instance) {
      StaffPerformanceReportService.instance = new StaffPerformanceReportService()
    }
    return StaffPerformanceReportService.instance
  }

  async getStaffPerformanceSummary(
    params: StaffPerformanceReportParams,
  ): Promise<StaffPerformanceReportResponse> {
    try {
      const searchParams = new URLSearchParams()
      searchParams.append('start_date', params.start_date)
      searchParams.append('end_date', params.end_date)

      const url = `/accounting/api/reports/staff-performance-summary/?${searchParams.toString()}`
      const response = await api.get<StaffPerformanceReportResponse>(url)
      return response.data
    } catch (error) {
      debugLog('Error fetching staff performance summary:', error)
      throw new Error('Failed to load staff performance summary')
    }
  }

  async getStaffPerformanceDetail(
    staffId: string,
    params: StaffPerformanceReportParams,
  ): Promise<StaffPerformanceReportResponse> {
    try {
      const searchParams = new URLSearchParams()
      searchParams.append('start_date', params.start_date)
      searchParams.append('end_date', params.end_date)

      const url = `/accounting/api/reports/staff-performance/${staffId}/?${searchParams.toString()}`
      const response = await api.get<StaffPerformanceReportResponse>(url)
      return response.data
    } catch (error) {
      debugLog('Error fetching staff performance detail:', error)
      throw new Error('Failed to load staff performance detail')
    }
  }

  exportToFile(staff: StaffPerformanceData[], teamAverages: TeamAverages, dateRange: string): void {
    const headers = [
      'Staff Name',
      'Total Hours',
      'Billable Hours',
      'Billable %',
      'Revenue per Hour',
      'Profit per Hour',
      'Jobs Worked',
      'Total Revenue',
      'Total Profit',
    ]

    const rows = staff.map((member) => [
      member.name,
      member.total_hours,
      member.billable_hours,
      member.billable_percentage,
      member.revenue_per_hour,
      member.profit_per_hour,
      member.jobs_worked,
      member.total_revenue,
      member.profit,
    ])

    // Build CSV with title and summary rows
    const titleRow = `"Staff Performance Report - ${dateRange}"`
    const summaryRow = `"Team Averages - Billable: ${teamAverages.billable_percentage}%, Revenue/hr: ${formatCurrency(teamAverages.revenue_per_hour)}, Profit/hr: ${formatCurrency(teamAverages.profit_per_hour)}"`
    const dataContent = toCsvString(headers, rows)
    const csvContent = [titleRow, summaryRow, '', dataContent].join('\n')

    downloadCsv(csvContent, `staff-performance-report-${toLocalDateString()}`)
  }

  getPerformanceComparison(
    staffValue: number,
    teamValue: number,
  ): {
    status: 'above' | 'below' | 'near'
    difference: number
    percentage: number
  } {
    const difference = staffValue - teamValue
    const percentage = teamValue > 0 ? Math.abs((difference / teamValue) * 100) : 0

    let status: 'above' | 'below' | 'near'
    if (percentage <= 5) {
      status = 'near'
    } else if (difference > 0) {
      status = 'above'
    } else {
      status = 'below'
    }

    return { status, difference, percentage }
  }

  getPerformanceVariant(status: 'above' | 'below' | 'near'): 'success' | 'warning' | 'danger' {
    switch (status) {
      case 'above':
        return 'success'
      case 'near':
        return 'warning'
      case 'below':
        return 'danger'
    }
  }

  formatCurrency(value: number): string {
    return formatCurrency(value)
  }

  formatHours(hours: number): string {
    return formatHoursDisplay(hours)
  }

  formatPercentage(percentage: number): string {
    return `${percentage.toFixed(0)}%`
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  detectProblems(staff: StaffPerformanceData, teamAverages: TeamAverages): string[] {
    // Problem detection rules should be set by the business, not hardcoded
    // Business can implement their own rules here based on their standards

    // Example business rule implementation:
    // const problems: string[] = []
    // if (staff.billable_percentage < teamAverages.billable_percentage - 10) {
    //   problems.push('Below team average for billable percentage')
    // }
    // return problems

    return []
  }
}

export const staffPerformanceReportService = StaffPerformanceReportService.getInstance()
