import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

export type DjangoJob = z.infer<typeof schemas.DjangoJob>
export type DjangoJobExecution = z.infer<typeof schemas.DjangoJobExecution>

export async function getDjangoJobs(): Promise<DjangoJob[]> {
  return await api.quoting_api_django_jobs_list()
}

export async function createDjangoJob(data: DjangoJob): Promise<DjangoJob> {
  return await api.quoting_api_django_jobs_create(data)
}

export async function updateDjangoJob(id: string, data: Partial<DjangoJob>): Promise<DjangoJob> {
  return await api.quoting_api_django_jobs_update(data as DjangoJob, { params: { id } })
}

export async function deleteDjangoJob(id: string): Promise<void> {
  await api.quoting_api_django_jobs_destroy(undefined, { params: { id } })
}

export async function getDjangoJobExecutions(search?: string): Promise<DjangoJobExecution[]> {
  return await api.quoting_api_django_job_executions_list(search ? { queries: { search } } : {})
}
