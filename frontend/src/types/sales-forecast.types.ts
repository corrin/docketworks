export interface SalesForecastMonth {
  month: string // Format: "YYYY-MM"
  month_label: string // Format: "MMM YYYY"
  xero_sales: number
  jm_sales: number
  variance: number
  variance_pct: number
}

export interface SalesForecastReportResponse {
  months: SalesForecastMonth[]
}

export interface SalesForecastDetailRow {
  date: string
  client_name: string
  job_number: number | null
  job_name: string | null
  job_id: string | null
  job_start_date: string | null
  invoice_numbers: string | null
  total_invoiced: number
  job_revenue: number
  variance: number
  note: string | null
  total_xero_all_time: number | null
  total_jm_all_time: number | null
  variance_all_time: number | null
}

export interface SalesForecastMonthDetailResponse {
  month: string
  month_label: string
  rows: SalesForecastDetailRow[]
}
