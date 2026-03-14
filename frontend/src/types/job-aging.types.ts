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

export interface JobAgingFilters {
  includeArchived: boolean
  statusFilter: string[]
  ageRange: {
    min: number
    max: number
  }
  lastActivityThreshold: number | null
}

export type ActivityAgeStatus = 'recent' | 'warning' | 'stale'
export type JobAgeStatus = 'new' | 'moderate' | 'old'

export interface JobAgingTableColumn {
  key: string
  label: string
  sortable: boolean
  width?: string
  align?: 'left' | 'center' | 'right'
}
