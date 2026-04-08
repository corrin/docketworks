import api from '@/plugins/axios'
import type { ProfitLossReportResponse, ProfitLossParams } from '@/types/profit-loss.types'

export const profitLossReportService = {
  async getProfitLossReport(params: ProfitLossParams): Promise<ProfitLossReportResponse> {
    const response = await api.get<ProfitLossReportResponse>(
      '/api/accounting/reports/profit-and-loss/',
      { params },
    )
    return response.data
  },
}
