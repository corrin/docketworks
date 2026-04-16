import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import { exportToCsv } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'

export interface WIPJobData {
  job_number: number
  name: string
  client: string
  status: string
  time_cost: number
  time_rev: number
  material_cost: number
  material_rev: number
  adjust_cost: number
  adjust_rev: number
  total_cost: number
  total_rev: number
  invoiced: number
  gross_wip: number
  net_wip: number
}

export interface WIPSummaryByStatus {
  status: string
  count: number
  net_wip: number
}

export interface WIPSummary {
  job_count: number
  total_gross: number
  total_invoiced: number
  total_net: number
  by_status: WIPSummaryByStatus[]
}

export interface WIPReportResponse {
  jobs: WIPJobData[]
  archived_jobs: WIPJobData[]
  summary: WIPSummary
  report_date: string
  method: 'revenue' | 'cost'
}

export interface WIPReportParams {
  date?: string
  method?: 'revenue' | 'cost'
}

export class WIPReportService {
  private static instance: WIPReportService

  static getInstance(): WIPReportService {
    if (!WIPReportService.instance) {
      WIPReportService.instance = new WIPReportService()
    }
    return WIPReportService.instance
  }

  async getWIPReport(params: WIPReportParams = {}): Promise<WIPReportResponse> {
    try {
      const queries: Record<string, string> = {
        ...(params.date && { date: params.date }),
        ...(params.method && { method: params.method }),
      }
      return (await api.accounting_reports_wip_retrieve({ queries })) as WIPReportResponse
    } catch (error) {
      debugLog('Error fetching WIP report:', error)
      throw new Error('Failed to load WIP report')
    }
  }

  exportToFile(jobs: WIPJobData[], method: 'revenue' | 'cost', reportDate: string): void {
    const valueLabel = method === 'revenue' ? 'Revenue' : 'Cost'
    const headers = [
      'Job Number',
      'Job Name',
      'Client',
      'Status',
      `Time (${valueLabel})`,
      `Material (${valueLabel})`,
      `Adjust (${valueLabel})`,
      'Gross WIP',
      'Invoiced',
      'Net WIP',
    ]

    const rows = jobs.map((job) => [
      job.job_number,
      job.name,
      job.client,
      job.status,
      method === 'revenue' ? job.time_rev : job.time_cost,
      method === 'revenue' ? job.material_rev : job.material_cost,
      method === 'revenue' ? job.adjust_rev : job.adjust_cost,
      job.gross_wip,
      job.invoiced,
      job.net_wip,
    ])

    exportToCsv(headers, rows, `wip-report-${reportDate || toLocalDateString()}`)
  }
}

export const wipReportService = WIPReportService.getInstance()
