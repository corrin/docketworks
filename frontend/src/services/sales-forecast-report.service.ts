import { api } from '@/api/client'
import type {
  SalesForecastReportResponse,
  SalesForecastMonthDetailResponse,
} from '@/types/sales-forecast.types'

export const salesForecastReportService = {
  async getSalesForecast(): Promise<SalesForecastReportResponse> {
    return (await api.sales_forecast_list()) as SalesForecastReportResponse
  },

  async getMonthDetail(month: string): Promise<SalesForecastMonthDetailResponse> {
    return (await api.sales_forecast_month_detail({
      params: { month },
    })) as SalesForecastMonthDetailResponse
  },
}
