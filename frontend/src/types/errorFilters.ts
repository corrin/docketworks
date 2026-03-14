export interface SystemErrorFilterState {
  app: string
  severity: string
  resolved: 'all' | 'true' | 'false'
  jobId: string
  userId: string
}

export interface JobErrorFilterState {
  jobId: string
}
