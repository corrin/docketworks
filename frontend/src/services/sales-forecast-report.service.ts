import api from '@/plugins/axios'
import type {
  SalesForecastReportResponse,
  SalesForecastMonthDetailResponse,
} from '@/types/sales-forecast.types'

export const salesForecastReportService = {
  async getSalesForecast(): Promise<SalesForecastReportResponse> {
    const response = await api.get<SalesForecastReportResponse>(
      '/accounting/api/reports/sales-forecast/',
    )
    return response.data
  },

  async getMonthDetail(month: string): Promise<SalesForecastMonthDetailResponse> {
    const response = await api.get<SalesForecastMonthDetailResponse>(
      `/accounting/api/reports/sales-forecast/${month}/`,
    )
    return response.data
  },
}
