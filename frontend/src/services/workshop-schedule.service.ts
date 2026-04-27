import { z } from 'zod'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { debugLog } from '@/utils/debug'

export type WorkshopScheduleResponse = z.infer<typeof schemas.WorkshopScheduleResponse>
export type ScheduledJob = z.infer<typeof schemas.ScheduledJob>
export type UnscheduledJob = z.infer<typeof schemas.UnscheduledJob>
export type ScheduleDay = z.infer<typeof schemas.Day>
export type AssignedStaff = z.infer<typeof schemas.AssignedStaff>
export type Staff = z.infer<typeof schemas.Staff>
export type AssignJobResponse = z.infer<typeof schemas.AssignJobResponse>

export const workshopScheduleService = {
  async getSchedule(dayHorizon?: number): Promise<WorkshopScheduleResponse> {
    debugLog('[workshopScheduleService.getSchedule] ->', { dayHorizon })
    const queries = dayHorizon !== undefined ? { day_horizon: dayHorizon } : {}
    return api.operations_workshop_schedule_retrieve({ queries })
  },

  async recalculate(dayHorizon?: number): Promise<WorkshopScheduleResponse> {
    debugLog('[workshopScheduleService.recalculate] ->', { dayHorizon })
    const queries = dayHorizon !== undefined ? { day_horizon: dayHorizon } : {}
    return api.operations_workshop_schedule_recalculate_create(undefined, { queries })
  },

  async listWorkshopStaff(): Promise<Staff[]> {
    debugLog('[workshopScheduleService.listWorkshopStaff] ->')
    const all = await api.accounts_staff_list()
    const today = new Date().toISOString().slice(0, 10)
    return all.filter((s) => s.is_workshop_staff === true && (!s.date_left || s.date_left > today))
  },

  async assignStaff(jobId: string, staffId: string): Promise<AssignJobResponse> {
    debugLog('[workshopScheduleService.assignStaff] ->', { jobId, staffId })
    return api.job_job_assignment_create({ staff_id: staffId }, { params: { job_id: jobId } })
  },

  async unassignStaff(jobId: string, staffId: string): Promise<AssignJobResponse> {
    debugLog('[workshopScheduleService.unassignStaff] ->', { jobId, staffId })
    return api.job_job_assignment_destroy(undefined, {
      params: { job_id: jobId, staff_id: staffId },
    })
  },
}

export default workshopScheduleService
