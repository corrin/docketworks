import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import type { SalesPipelineReportParams, SalesPipelineResponse } from '@/types/sales-pipeline.types'

export const salesPipelineReportService = {
  async getSalesPipelineReport(params: SalesPipelineReportParams): Promise<SalesPipelineResponse> {
    try {
      return (await api.accounting_reports_sales_pipeline_retrieve({
        queries: params,
      })) as unknown as SalesPipelineResponse
    } catch (error) {
      debugLog('Error fetching sales pipeline report:', error)
      throw new Error('Failed to load sales pipeline report')
    }
  },

  /**
   * Fetch the current headline window AND a baseline window in parallel.
   *
   * The redesigned Sales Pipeline Report compares every "now" number to a
   * trailing-12-week baseline so the head of sales never sees a bare metric.
   * Two GETs hit `/api/accounting/reports/sales-pipeline/` simultaneously; the
   * caller scales the baseline to the headline window's length client-side.
   *
   * Both calls go through the same generated client, so warnings, etag, and
   * error handling are identical to the single-window method.
   */
  async getCurrentAndBaseline(args: {
    current: SalesPipelineReportParams
    baseline: SalesPipelineReportParams
  }): Promise<{ current: SalesPipelineResponse; baseline: SalesPipelineResponse }> {
    const [current, baseline] = await Promise.all([
      this.getSalesPipelineReport(args.current),
      this.getSalesPipelineReport(args.baseline),
    ])
    return { current, baseline }
  },
}
