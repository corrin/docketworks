import { z } from 'zod'
import { schemas } from '@/api/generated/api'

export interface StaffPerformanceReportParams {
  start_date: string
  end_date: string
}

export type StaffPerformanceData = z.infer<typeof schemas.StaffPerformanceStaffData>

export type TeamAverages = z.infer<typeof schemas.StaffPerformanceTeamAverages>

export type StaffPerformanceReportResponse = z.infer<typeof schemas.StaffPerformanceResponse>
