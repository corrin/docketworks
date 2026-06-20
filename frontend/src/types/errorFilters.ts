export interface SystemErrorFilterState {
  app: string
  severity: string
  resolved: 'true' | 'false'
  jobId: string
  userId: string
}

export interface JobErrorFilterState {
  jobId: string
  resolved: 'true' | 'false'
}
