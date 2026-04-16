import { api } from '@/api/client'
import type { JobMovementParams, JobMovementReportResponse } from '@/types/job-movement.types'

export const jobMovementReportService = {
  async getJobMovementReport(params: JobMovementParams): Promise<JobMovementReportResponse> {
    return (await api.accounting_reports_job_movement_retrieve({
      queries: params,
    })) as unknown as JobMovementReportResponse
  },
}
