import api from '@/plugins/axios'
import { debugLog } from '@/utils/debug'
import { exportToCsv } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'

export interface JobAgingData {
  id: string
  job_number: number
  name: string
  client_name: string
  status: string
  status_display: string
  financial_data: {
    estimate_total: number
    quote_total: number
    actual_total: number
  }
  timing_data: {
    created_date: string
    created_days_ago: number
    days_in_current_status: number
    last_activity_date: string
    last_activity_days_ago: number
    last_activity_type: string
    last_activity_description: string
  }
}

export interface JobAgingReportResponse {
  jobs: JobAgingData[]
}

export interface JobAgingReportParams {
  include_archived?: boolean
}

export class JobAgingReportService {
  private static instance: JobAgingReportService

  static getInstance(): JobAgingReportService {
    if (!JobAgingReportService.instance) {
      JobAgingReportService.instance = new JobAgingReportService()
    }
    return JobAgingReportService.instance
  }

  async getJobAgingReport(params: JobAgingReportParams = {}): Promise<JobAgingReportResponse> {
    try {
      const searchParams = new URLSearchParams()
      if (params.include_archived) {
        searchParams.append('include_archived', 'true')
      }

      const queryString = searchParams.toString()
      const url = `/accounting/api/reports/job-aging/${queryString ? `?${queryString}` : ''}`

      const response = await api.get<JobAgingReportResponse>(url)
      return response.data
    } catch (error) {
      debugLog('Error fetching job aging report:', error)
      throw new Error('Failed to load job aging report')
    }
  }

  exportToFile(jobs: JobAgingData[]): void {
    const headers = [
      'Job Number',
      'Job Name',
      'Client Name',
      'Status',
      'Days in Status',
      'Job Age (Days)',
      'Last Activity',
      'Last Activity Type',
      'Estimate Total',
      'Quote Total',
      'Actual Total',
    ]

    const rows = jobs.map((job) => [
      job.job_number,
      job.name,
      job.client_name,
      job.status_display,
      job.timing_data.days_in_current_status,
      job.timing_data.created_days_ago,
      job.timing_data.last_activity_days_ago,
      job.timing_data.last_activity_type,
      job.financial_data.estimate_total,
      job.financial_data.quote_total,
      job.financial_data.actual_total,
    ])

    exportToCsv(headers, rows, `job-aging-report-${toLocalDateString()}`)
  }

  getActivityAgeStatus(daysAgo: number): 'recent' | 'warning' | 'stale' {
    if (daysAgo <= 7) return 'recent'
    if (daysAgo <= 30) return 'warning'
    return 'stale'
  }

  getJobAgeStatus(daysAgo: number): 'new' | 'moderate' | 'old' {
    if (daysAgo <= 30) return 'new'
    if (daysAgo <= 90) return 'moderate'
    return 'old'
  }
}

export const jobAgingReportService = JobAgingReportService.getInstance()
