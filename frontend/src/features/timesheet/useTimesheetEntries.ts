import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  approveCostLineMutation,
  jobCostLinesDeleteDestroyMutation,
  jobCostLinesPartialUpdateMutation,
  jobJobsCostSetsActualCostLinesCreateMutation,
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
import { restoreDeletedRow } from '@/features/shared/optimistic'

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
 * and nowhere else — the useCostLines discipline rebound to the
 * (staff_id, date) entries envelope. Writes are optimistic with rollback;
 * every failure toasts (the E2E console guard fails a spec on console.error).
 *
 * Pricing is server-owned: any PATCH carrying meta (or labour_subtype) on a
 * created_from_timesheet line runs the one rate pipeline server-side, so the
 * echo merge always applies the pricing outputs (unit_cost, unit_rev,
 * xero_pay_item, labour_subtype, meta, totals) — the client never computes a
 * price it could get wrong.
 */
export function useTimesheetEntries(staffId: string, date: string) {
  const queryClient = useQueryClient()
  const query = { staff_id: staffId, date }
  const queryKey = jobTimesheetEntriesRetrieveQueryKey({ query })
  const entriesQuery = useQuery(jobTimesheetEntriesRetrieveOptions({ query }))

  const patchMutation = useMutation(jobCostLinesPartialUpdateMutation())
  const createMutation = useMutation(jobJobsCostSetsActualCostLinesCreateMutation())
  const deleteMutation = useMutation(jobCostLinesDeleteDestroyMutation())
  const approveMutation = useMutation(approveCostLineMutation())

  const invalidate = () => void queryClient.invalidateQueries({ queryKey })
  // An in-flight background refetch resolving AFTER an optimistic write
  // would clobber it with pre-write data; cancellation closes that window.
  const cancelInFlight = () => void queryClient.cancelQueries({ queryKey })

  const setLines = (map: (lines: TimesheetCostLineOut[]) => TimesheetCostLineOut[]) => {
    const current = queryClient.getQueryData<TimesheetEntriesOut>(queryKey)
    if (!current) return
    queryClient.setQueryData<TimesheetEntriesOut>(queryKey, {
      ...current,
      cost_lines: map(current.cost_lines),
    })
  }

  const patchLine = (lineId: string, body: CostLineUpdateRequest) => {
    cancelInFlight()
    const snapshot = queryClient.getQueryData<TimesheetEntriesOut>(queryKey)
    const snapshotLine = snapshot?.cost_lines.find((line) => line.id === lineId)
    setLines((lines) =>
      lines.map((line) => (line.id === lineId ? applyPatchForDisplay(line, body) : line)),
    )
    patchMutation.mutate(
      { path: { cost_line_id: lineId }, body },
      {
        onSuccess: (updated) => {
          setLines((lines) =>
            lines.map((line) => (line.id === lineId ? mergeTimesheetEcho(line, updated) : line)),
          )
        },
        onError: (error) => {
          // Per-field rollback against the CURRENT cache, not a wholesale
          // snapshot restore: interleaved patches each roll back only their
          // own fields (the useCostLines rule).
          if (snapshotLine) {
            setLines((lines) =>
              lines.map((line) =>
                line.id === lineId ? revertPatchFields(line, snapshotLine, body) : line,
              ),
            )
          }
          toast.error(apiErrorMessage(error, 'Failed to save the timesheet entry'))
        },
        onSettled: invalidate,
      },
    )
  }

  const createLine = (
    job: TimesheetJobOut,
    body: TimesheetCreateBody,
    { onCreated, onFailed }: CreateEntryCallbacks,
  ) => {
    createMutation.mutate(
      { path: { job_id: job.id }, body: { kind: 'time', ...body } },
      {
        onSuccess: (created) => {
          // The job router's line has no job-identity fields; the picked job
          // supplies them so the row renders before the reconciling refetch.
          const enriched = enrichWithJob(created, job)
          setLines((lines) => [...lines, enriched])
          onCreated(enriched)
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to add the timesheet entry'))
          onFailed()
        },
        onSettled: invalidate,
      },
    )
  }

  const deleteLine = (lineId: string) => {
    cancelInFlight()
    const snapshot = queryClient.getQueryData<TimesheetEntriesOut>(queryKey)
    setLines((lines) => lines.filter((line) => line.id !== lineId))
    deleteMutation.mutate(
      { path: { cost_line_id: lineId } },
      {
        onError: (error) => {
          // Re-insert only the deleted line into the CURRENT cache — a
          // wholesale snapshot restore would resurrect other lines' rejected
          // optimistic values.
          if (snapshot) {
            setLines((lines) => restoreDeletedRow(lines, snapshot.cost_lines, lineId))
          }
          toast.error(apiErrorMessage(error, 'Failed to delete the timesheet entry'))
        },
        onSettled: invalidate,
      },
    )
  }

  const approveLine = (lineId: string) => {
    approveMutation.mutate(
      { path: { cost_line_id: lineId } },
      {
        onSuccess: (response) => {
          setLines((lines) =>
            lines.map((line) =>
              line.id === lineId ? mergeTimesheetEcho(line, response.line) : line,
            ),
          )
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to approve the timesheet entry'))
        },
        onSettled: invalidate,
      },
    )
  }

  return { entriesQuery, patchLine, createLine, deleteLine, approveLine }
}

function enrichWithJob(line: CostLineOut, job: TimesheetJobOut): TimesheetCostLineOut {
  return {
    ...line,
    job_id: job.id,
    job_number: job.job_number,
    job_name: job.name,
    company_name: job.company_name ?? null,
  }
}

/** Optimistic display value; the echo and settle refetch replace it. */
function applyPatchForDisplay(
  line: TimesheetCostLineOut,
  body: CostLineUpdateRequest,
): TimesheetCostLineOut {
  const next: TimesheetCostLineOut = { ...line }
  if (body.desc !== undefined) next.desc = body.desc
  if (body.quantity !== undefined) next.quantity = String(body.quantity)
  if (body.meta !== undefined) next.meta = body.meta
  if (body.labour_subtype !== undefined) next.labour_subtype = body.labour_subtype
  return next
}

/**
 * Merge a write's echo, keeping the row's job identity (the job router's
 * echo has none). Pricing outputs apply unconditionally — the server derives
 * them from meta + quantity on every timesheet-line write.
 */
export function mergeTimesheetEcho(
  line: TimesheetCostLineOut,
  echo: CostLineOut,
): TimesheetCostLineOut {
  return {
    ...line,
    desc: echo.desc,
    quantity: echo.quantity,
    unit_cost: echo.unit_cost,
    unit_rev: echo.unit_rev,
    meta: echo.meta,
    xero_pay_item: echo.xero_pay_item,
    labour_subtype: echo.labour_subtype,
    approved: echo.approved,
    entry_seq: echo.entry_seq,
    total_cost: echo.total_cost,
    total_rev: echo.total_rev,
    updated_at: echo.updated_at,
  }
}

/** Undo exactly the fields a rejected patch touched, from the pre-patch line. */
function revertPatchFields(
  line: TimesheetCostLineOut,
  snapshotLine: TimesheetCostLineOut,
  body: CostLineUpdateRequest,
): TimesheetCostLineOut {
  const next: TimesheetCostLineOut = { ...line }
  if (body.desc !== undefined) next.desc = snapshotLine.desc
  if (body.quantity !== undefined) next.quantity = snapshotLine.quantity
  if (body.meta !== undefined) next.meta = snapshotLine.meta
  if (body.labour_subtype !== undefined) next.labour_subtype = snapshotLine.labour_subtype
  return next
}
