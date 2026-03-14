// Types for the Job Movement Metrics Report API

export interface JobMovementParams {
  start_date: string // YYYY-MM-DD
  end_date: string // YYYY-MM-DD
  baseline_days?: number // e.g., 365
  compare_start_date?: string
  compare_end_date?: string
  include_details?: boolean
}

export interface JobMovementMetricCount {
  count: number
  comparison_value?: number
  change?: number
  change_percent?: number
}

export interface JobMovementRateMetric {
  rate: number
  numerator: number
  denominator: number
}

export interface JobsWonMetric {
  count: number
  still_draft: number
  rejected: number
  total_created: number
  comparison_value?: number
  change?: number
  change_percent?: number
}

export interface WorkflowPaths {
  through_quotes: number
  skip_quotes: number
  still_draft: number
  quote_usage_percent: number
}

export interface JobMovementMetrics {
  draft_jobs_created: JobMovementMetricCount
  quotes_submitted: JobMovementMetricCount
  quotes_accepted: JobMovementMetricCount
  quote_acceptance_rate: JobMovementRateMetric
  jobs_won: JobsWonMetric
  draft_conversion_rate: JobMovementRateMetric
  workflow_paths: WorkflowPaths
}

export interface JobMovementBaselineTotals {
  draft_jobs_created: number
  quotes_submitted: number
  quotes_accepted: number
  jobs_won: number
  rejected: number
  through_quotes: number
  skip_quotes: number
}

export interface JobMovementBaselineWeeklyAverages {
  draft_jobs_created: number
  quotes_submitted: number
  quotes_accepted: number
  jobs_won: number
  rejected: number
}

export interface JobMovementBaselineRates {
  quote_acceptance_rate: number
  draft_conversion_rate: number
  quote_usage_rate: number
}

export interface JobMovementBaseline {
  period_days: number
  weeks: number
  totals: JobMovementBaselineTotals
  weekly_averages: JobMovementBaselineWeeklyAverages
  rates: JobMovementBaselineRates
}

export interface JobMovementPeriod {
  start_date: string
  end_date: string
  days: number
}

export interface JobMovementJobDetail {
  id: string
  job_number: string
  name: string
  client_name: string
  status: string
  created_at: string
}

export interface JobMovementDetails {
  draft_jobs: JobMovementJobDetail[]
  quotes_submitted: JobMovementJobDetail[]
  quotes_accepted: JobMovementJobDetail[]
  jobs_won: JobMovementJobDetail[]
  jobs_still_draft: JobMovementJobDetail[]
  jobs_rejected: JobMovementJobDetail[]
}

export interface JobMovementReportResponse {
  period: JobMovementPeriod
  metrics: JobMovementMetrics
  baseline?: JobMovementBaseline
  comparison_period?: JobMovementPeriod
  details?: JobMovementDetails
}
