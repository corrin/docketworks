import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import {
  approveCostLineMutation,
  jobTimesheetEntriesRetrieve,
  jobTimesheetEntriesRetrieveOptions,
  jobTimesheetEntriesRetrieveQueryKey,
  jobWorkshopTimesheetsCreateMutation,
  jobWorkshopTimesheetsDestroyMutation,
  jobWorkshopTimesheetsPartialUpdateMutation,
} from '@/api'
import type {
  TimesheetCostLineOut,
  TimesheetEntriesOut,
  TimesheetJobOut,
  WorkshopTimesheetEntryRequest,
  WorkshopTimesheetEntryUpdateRequest,
} from '@/api'
import { useOptimisticRows } from '@/features/shared/optimistic'

/** A new entry from the grid: the job comes from the row's pick. */
export type TimesheetCreateBody = Omit<WorkshopTimesheetEntryRequest, 'job_id' | 'location'>
/** An edit to a saved entry, whichever field the grid changed. */
export type TimesheetEntryEdit = Omit<WorkshopTimesheetEntryUpdateRequest, 'entry_id' | 'location'>

export interface CreateEntryCallbacks {
  onCreated: (line: TimesheetCostLineOut) => void
  onFailed: () => void
  /** The save was stopped (he cancelled the overtime question): the draft stays as typed. */
  onCancelled: () => void
}

/** The queries that show a person's entries, by their generated names. */
const ENTRY_VIEWS = new Set([
  'jobTimesheetEntriesRetrieve',
  'jobTimesheetEntriesHistoryRetrieve',
  'jobWorkshopTimesheetsRetrieve',
  'timesheetsApprovalsRetrieve',
])

/**
 * Every view of a person's entries goes stale together: the office grid and
 * its history, the my-time day and Approve time. A write can move an entry
 * to another day or person's view, so each is invalidated whole, not by date.
 */
export function invalidateEntryViews(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({
    predicate: ({ queryKey: [first] }) =>
      typeof first === 'object' &&
      first !== null &&
      '_id' in first &&
      ENTRY_VIEWS.has(String(first['_id'])),
  })
}

/**
 * All server state for one staff member's day, in the TanStack Query cache
 * and nowhere else, written through the shared optimistic runner (serialized
 * per day, rollback on refusal, every failure toasts).
 *
 * Writes go through the timesheet entry endpoints, the same ones the my-time
 * drawer uses, so one writer places, prices and splits every entry. Pricing
 * is server-owned: an edit shows its own fields at once, and the read after
 * the queue settles brings the prices back. The entry endpoints answer with
 * an entry, not a priced line, so a new row is read back from the day.
 */
export function useTimesheetEntries(staffId: string, date: string) {
  const { t } = useTranslation('timesheet')
  const queryClient = useQueryClient()
  const query = { staff_id: staffId, date }
  const queryKey = jobTimesheetEntriesRetrieveQueryKey({ query })

  const grid = useOptimisticRows<TimesheetEntriesOut, TimesheetCostLineOut>({
    queryKey,
    rows: (day) => day.cost_lines,
    withRows: (day, cost_lines) => ({ ...day, cost_lines }),
    scopeId: `timesheet-day:${staffId}:${date}`,
    invalidate: () => invalidateEntryViews(queryClient),
  })

  const entriesQuery = useQuery({
    ...jobTimesheetEntriesRetrieveOptions({ query }),
    enabled: grid.canRefetch,
  })
  const updateMutation = useMutation(grid.serialized(jobWorkshopTimesheetsPartialUpdateMutation()))
  const createMutation = useMutation(grid.serialized(jobWorkshopTimesheetsCreateMutation()))
  const deleteMutation = useMutation(grid.serialized(jobWorkshopTimesheetsDestroyMutation()))
  const approveMutation = useMutation(grid.serialized(approveCostLineMutation()))

  const patchLine = (line: TimesheetCostLineOut, edit: TimesheetEntryEdit) =>
    grid.patchRow(
      line.id,
      entryDisplay(line, edit),
      () =>
        updateMutation.mutateAsync({ body: { entry_id: line.id, ...edit } }).then(() => undefined),
      t('entries.saveFailed'),
    )

  /** Move a saved entry to another job: the picked job is the display, the read reprices it. */
  const moveLine = (lineId: string, job: TimesheetJobOut) =>
    grid.patchRow(
      lineId,
      jobIdentity(job),
      () =>
        updateMutation
          .mutateAsync({ body: { entry_id: lineId, job_id: job.id } })
          .then(() => undefined),
      t('entries.moveFailed'),
    )

  const createLine = (
    job: TimesheetJobOut,
    body: TimesheetCreateBody,
    callbacks: CreateEntryCallbacks,
  ) =>
    grid.appendRow(
      async () => {
        const created = await createMutation.mutateAsync({
          body: { ...body, job_id: job.id, staff_id: staffId },
        })
        // The runner appends the row to its own copy of the day, so this
        // read only finds the priced line; it bypasses the cache, which the
        // runner owns while the queue is busy.
        const { data: day } = await jobTimesheetEntriesRetrieve({ query, throwOnError: true })
        const line = day.cost_lines.find((each) => each.id === created.id)
        if (line === undefined) throw new Error(`Saved entry ${created.id} is not on its day`)
        return line
      },
      callbacks,
      t('entries.addFailed'),
    )

  const deleteLine = (lineId: string) =>
    grid.deleteRow(
      lineId,
      () => deleteMutation.mutateAsync({ query: { entry_id: lineId } }),
      t('entries.deleteFailed'),
    )

  const approveLine = (lineId: string) =>
    grid.patchRow(
      lineId,
      {},
      () =>
        approveMutation
          .mutateAsync({ path: { cost_line_id: lineId } })
          .then((response) => response.line),
      t('entries.approveFailed'),
    )

  return { entriesQuery, patchLine, moveLine, createLine, deleteLine, approveLine }
}

/** What an edit changes on the row, shown before the server answers. */
function entryDisplay(
  line: TimesheetCostLineOut,
  edit: TimesheetEntryEdit,
): Partial<TimesheetCostLineOut> {
  const display: Partial<TimesheetCostLineOut> = {}
  if (edit.hours !== undefined) display.quantity = String(edit.hours)
  if (edit.description !== undefined) display.desc = edit.description
  if (edit.labour_subtype_id !== undefined) display.labour_subtype = edit.labour_subtype_id
  const meta = { ...line.meta }
  if (edit.wage_rate_multiplier !== undefined)
    meta.wage_rate_multiplier = Number(edit.wage_rate_multiplier)
  if (edit.bill_rate_multiplier !== undefined)
    meta.bill_rate_multiplier = Number(edit.bill_rate_multiplier)
  if (edit.is_billable !== undefined) meta.is_billable = edit.is_billable
  display.meta = meta
  return display
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
