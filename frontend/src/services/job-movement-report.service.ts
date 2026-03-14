import api from '@/plugins/axios'
import type { JobMovementParams, JobMovementReportResponse } from '@/types/job-movement.types'

export const jobMovementReportService = {
  async getJobMovementReport(params: JobMovementParams): Promise<JobMovementReportResponse> {
    const response = await api.get<JobMovementReportResponse>(
      '/accounting/api/reports/job-movement/',
      { params },
    )
    return response.data
  },
}
