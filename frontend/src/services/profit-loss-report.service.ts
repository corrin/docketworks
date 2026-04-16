import { api } from '@/api/client'
import type { ProfitLossReportResponse, ProfitLossParams } from '@/types/profit-loss.types'

export const profitLossReportService = {
  async getProfitLossReport(params: ProfitLossParams): Promise<ProfitLossReportResponse> {
    return (await api.accounting_reports_profit_and_loss_retrieve({
      queries: {
        start_date: params.start_date,
        end_date: params.end_date,
        ...(params.compare_periods !== undefined && { compare: params.compare_periods }),
        ...(params.period_length !== undefined &&
          params.period_length !== 'quarter' && { period_type: params.period_length }),
      },
    })) as unknown as ProfitLossReportResponse
  },
}
