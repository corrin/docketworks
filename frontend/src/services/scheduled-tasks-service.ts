import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

export type ScheduledTask = z.infer<typeof schemas.ScheduledTask>
export type TaskExecution = z.infer<typeof schemas.ScheduledTaskExecution>

export async function getScheduledTasks(): Promise<ScheduledTask[]> {
  return await api.quoting_scheduled_tasks_list()
}

export async function getTaskExecutions(taskName?: string): Promise<TaskExecution[]> {
  return await api.quoting_scheduled_task_executions_list(
    taskName ? { queries: { search: taskName } } : {},
  )
}
