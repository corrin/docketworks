import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  approveCostLineMutation,
  jobCostLinesDeleteDestroyMutation,
  jobCostLinesPartialUpdateMutation,
  jobJobsCostSetsActualCostLinesCreateMutation,
  jobTimesheetEntriesHistoryRetrieveQueryKey,
  jobTimesheetEntriesRetrieveOptions,
  jobTimesheetEntriesRetrieveQueryKey,
} from '@/api'
import type {
  CostLineOut,
  CostLineUpdateRequest,
  TimesheetCostLineOut,
  TimesheetEntriesOut,
  TimesheetJobOut,
} from '@/api'
import { costLineDisplay } from '@/features/shared/costLineDisplay'
import { useOptimisticRows } from '@/features/shared/optimistic'

export interface TimesheetCreateBody {
  /** Null when blank — CostLine pins desc_not_blank (unset is NULL, ADR 0040). */
  desc: string | null
  quantity: string
  accounting_date: string
  meta: {
    staff_id: string
    date: string
    is_billable: boolean
    wage_rate_multiplier: number
    bill_rate_multiplier: number
    created_from_timesheet: true
  }
  labour_subtype?: string
}

interface CreateEntryCallbacks {
  onCreated: (line: TimesheetCostLineOut) => void
  onFailed: () => void
}

/**
 * All server state for one staff member's day, in the TanStack Query cache
 * and nowhere else, written through the shared optimistic runner (serialized
 * per day, rollback on refusal, every failure toasts).
 *
 * Pricing is server-owned: any PATCH carrying meta (or labour_subtype) on a
 * created_from_timesheet line runs the one rate pipeline server-side, and the
 * echo carries every pricing output — the client never computes a price it
 * could get wrong. The echo is a job-router line with no job identity, so
 * merging it over the cached row keeps the row's job fields, which is what a
 * move relies on.
 */
export function useTimesheetEntries(staffId: string, date: string) {
  const queryClient = useQueryClient()
  const query = { staff_id: staffId, date }
  const queryKey = jobTimesheetEntriesRetrieveQueryKey({ query })
  const historyKey = jobTimesheetEntriesHistoryRetrieveQueryKey({ query })
  const entriesQuery = useQuery(jobTimesheetEntriesRetrieveOptions({ query }))

  const grid = useOptimisticRows<TimesheetEntriesOut, TimesheetCostLineOut>({
    queryKey,
    rows: (day) => day.cost_lines,
    withRows: (day, cost_lines) => ({ ...day, cost_lines }),
    scopeId: `timesheet-day:${staffId}:${date}`,
    // Every write also records a TimesheetEvent, so the day's history is
    // stale after any of them.
    invalidate: () => {
      void queryClient.invalidateQueries({ queryKey })
      void queryClient.invalidateQueries({ queryKey: historyKey })
    },
  })

  const patchMutation = useMutation(grid.serialized(jobCostLinesPartialUpdateMutation()))
  const createMutation = useMutation(
    grid.serialized(jobJobsCostSetsActualCostLinesCreateMutation()),
  )
  const deleteMutation = useMutation(grid.serialized(jobCostLinesDeleteDestroyMutation()))
  const approveMutation = useMutation(grid.serialized(approveCostLineMutation()))

  const patchLine = (lineId: string, body: CostLineUpdateRequest) =>
    grid.patchRow(
      lineId,
      costLineDisplay(body),
      () => patchMutation.mutateAsync({ path: { cost_line_id: lineId }, body }),
      'Failed to save the timesheet entry',
    )

  /** Move a saved entry to another job: the picked job is the display, the echo reprices it. */
  const moveLine = (lineId: string, job: TimesheetJobOut) =>
    grid.patchRow(
      lineId,
      jobIdentity(job),
      () => patchMutation.mutateAsync({ path: { cost_line_id: lineId }, body: { job_id: job.id } }),
      'Failed to move the timesheet entry',
    )

  const createLine = (
    job: TimesheetJobOut,
    body: TimesheetCreateBody,
    callbacks: CreateEntryCallbacks,
  ) =>
    grid.appendRow(
      () =>
        createMutation
          .mutateAsync({ path: { job_id: job.id }, body: { kind: 'time', ...body } })
          // The job router's line has no job-identity fields; the picked job
          // supplies them so the row renders before the reconciling refetch.
          .then((created) => enrichWithJob(created, job)),
      callbacks,
      'Failed to add the timesheet entry',
    )

  const deleteLine = (lineId: string) =>
    grid.deleteRow(
      lineId,
      () => deleteMutation.mutateAsync({ path: { cost_line_id: lineId } }),
      'Failed to delete the timesheet entry',
    )

  const approveLine = (lineId: string) =>
    grid.patchRow(
      lineId,
      {},
      () =>
        approveMutation
          .mutateAsync({ path: { cost_line_id: lineId } })
          .then((response) => response.line),
      'Failed to approve the timesheet entry',
    )

  return { entriesQuery, patchLine, moveLine, createLine, deleteLine, approveLine }
}

type JobIdentity = Pick<TimesheetCostLineOut, 'job_id' | 'job_number' | 'job_name' | 'company_name'>

function jobIdentity(job: TimesheetJobOut): JobIdentity {
  return {
    job_id: job.id,
    job_number: job.job_number,
    job_name: job.name,
    company_name: job.company_name ?? null,
  }
}

function enrichWithJob(line: CostLineOut, job: TimesheetJobOut): TimesheetCostLineOut {
  return { ...line, ...jobIdentity(job) }
}
