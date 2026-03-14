import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type MonthEndJob = z.infer<typeof schemas.MonthEndJob>
type MonthEndStockJob = z.infer<typeof schemas.MonthEndStockJob>
type MonthEndGetResponse = z.infer<typeof schemas.MonthEndGetResponse>
type MonthEndPostResponse = z.infer<typeof schemas.MonthEndPostResponse>

export async function fetchMonthEnd(): Promise<{
  jobs: MonthEndJob[]
  stockJob: MonthEndStockJob
}> {
  // Note: Month parameter might need to be handled differently - check if endpoint supports query params
  const response: MonthEndGetResponse = await api.job_rest_month_end_retrieve()
  return { jobs: response.jobs, stockJob: response.stock_job }
}

export async function runMonthEnd(
  jobIds: string[],
): Promise<{ processed: string[]; errors: string[] }> {
  // Using proper request body format for month-end processing
  const response: MonthEndPostResponse = await api.job_rest_month_end_create({
    job_ids: jobIds,
  })
  return { processed: response.processed, errors: response.errors }
}
