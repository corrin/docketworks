export type PeriodPreset =
  | 'thisMonth'
  | 'thisQuarter'
  | 'thisFinancialYear'
  | 'lastMonth'
  | 'lastQuarter'
  | 'lastFinancialYear'
  | 'monthToDate'
  | 'yearToDate'

export type PeriodLength = 'month' | 'quarter' | 'year'

export interface ProfitLossParams {
  start_date: string // YYYY-MM-DD
  end_date: string // YYYY-MM-DD
  compare_periods?: number // Number of periods to compare (e.g., 1, 2, 3)
  period_length?: PeriodLength // Length of comparison period
}

export interface ProfitLossLineItem {
  account_code: string
  account_name: string
  amount: number
  compare_amounts?: number[] // Array of amounts for comparison periods
}

export interface ProfitLossSection {
  title: string
  line_items: ProfitLossLineItem[]
  total: number
  compare_totals?: number[] // Array of totals for comparison periods
}

export interface ProfitLossReportResponse {
  report_title: string
  start_date: string
  end_date: string
  compare_periods?: number
  period_length?: PeriodLength
  compare_period_labels?: string[] // Labels for comparison columns

  // Main sections
  revenue: ProfitLossSection
  cost_of_sales: ProfitLossSection
  gross_profit: {
    amount: number
    compare_amounts?: number[]
  }

  operating_expenses: ProfitLossSection
  net_profit: {
    amount: number
    compare_amounts?: number[]
  }
}
