import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobWorkshopTimesheetsCreateMutation,
  jobWorkshopTimesheetsDestroyMutation,
  jobWorkshopTimesheetsPartialUpdateMutation,
  jobWorkshopTimesheetsRetrieveOptions,
  jobWorkshopTimesheetsRetrieveQueryKey,
} from '@/api'
import type { WorkshopTimesheetEntryRequest, WorkshopTimesheetEntryUpdateRequest } from '@/api'

function report(error: unknown, fallback: string): void {
  toast.error(apiErrorMessage(error, fallback))
}

/**
 * One staff member's own day on the workshop calendar: the day query plus the
 * three self-service writes. Server state lives in the TanStack cache only.
 *
 * Writes settle before the UI moves on (the drawer stays open on failure), so
 * these are plain await-then-invalidate — no optimistic layer. Every failure
 * toasts: the E2E console guard fails a spec on an unhandled console.error.
 */
export function useWorkshopDay(date: string) {
  const queryClient = useQueryClient()
  const query = { date }
  const queryKey = jobWorkshopTimesheetsRetrieveQueryKey({ query })
  const dayQuery = useQuery(jobWorkshopTimesheetsRetrieveOptions({ query }))

  const createMutation = useMutation(jobWorkshopTimesheetsCreateMutation())
  const updateMutation = useMutation(jobWorkshopTimesheetsPartialUpdateMutation())
  const deleteMutation = useMutation(jobWorkshopTimesheetsDestroyMutation())

  // Entries carry an accounting_date, so a write can move one off this day —
  // every settle invalidates the whole surface (the optionless key partially
  // matches every date's key) rather than only this day's.
  const invalidateDays = () =>
    void queryClient.invalidateQueries({ queryKey: jobWorkshopTimesheetsRetrieveQueryKey() })

  /** True on success; the caller closes the drawer only then. */
  const createEntry = async (body: WorkshopTimesheetEntryRequest): Promise<boolean> => {
    try {
      await createMutation.mutateAsync({ body })
    } catch (error) {
      report(error, 'The entry could not be saved.')
      return false
    }
    invalidateDays()
    return true
  }

  const updateEntry = async (body: WorkshopTimesheetEntryUpdateRequest): Promise<boolean> => {
    try {
      await updateMutation.mutateAsync({ body })
    } catch (error) {
      report(error, 'The entry could not be updated.')
      return false
    }
    invalidateDays()
    return true
  }

  const deleteEntry = async (entryId: string): Promise<boolean> => {
    try {
      await deleteMutation.mutateAsync({ query: { entry_id: entryId } })
    } catch (error) {
      report(error, 'The entry could not be deleted.')
      return false
    }
    invalidateDays()
    return true
  }

  return {
    dayQuery,
    refetch: () => void dayQuery.refetch(),
    createEntry,
    updateEntry,
    deleteEntry,
    saving: createMutation.isPending || updateMutation.isPending || deleteMutation.isPending,
    queryKey,
  }
}
