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
import type {
  EntryLocationIn,
  WorkshopTimesheetEntryRequest,
  WorkshopTimesheetEntryUpdateRequest,
} from '@/api'

// Short enough that a phone with no signal does not leave the Save button
// looking dead. The position is read fresh for every save, never from the
// browser's cache: a remembered fix would vouch for a save made after the
// phone had left.
const LOCATION_TIMEOUT_MS = 5000

/**
 * Where the phone says it is, or null when it will not say: location refused,
 * no fix in time, or no position service. The server marks a worker's save
 * that arrives without a location at the company address, so null is an
 * answer, not a failure, and the save goes ahead either way.
 */
function phoneLocation(): Promise<EntryLocationIn | null> {
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve({ latitude: coords.latitude, longitude: coords.longitude }),
      () => resolve(null),
      { timeout: LOCATION_TIMEOUT_MS, maximumAge: 0 },
    )
  })
}

function report(error: unknown, fallback: string): void {
  toast.error(apiErrorMessage(error, fallback))
}

/**
 * One staff member's own day on the workshop calendar: the day query plus the
 * three self-service writes. Server state lives in the TanStack cache only.
 *
 * Fable: Writes settle before the UI moves on (the drawer stays open on
 * failure), so these are plain await-then-invalidate — the optimistic layer
 * useTimesheetEntries carries exists for a grid whose focus keeps moving,
 * which a modal drawer does not have. Every failure toasts: the E2E console
 * guard fails a spec on an unhandled console.error.
 *
 * `sendLocation` is whether a save carries the phone's location: only for
 * workshop staff of a company whose address is set, so nobody else is asked.
 */
export function useWorkshopDay(date: string, sendLocation: boolean) {
  const queryClient = useQueryClient()
  const query = { date }
  const queryKey = jobWorkshopTimesheetsRetrieveQueryKey({ query })
  const dayQuery = useQuery(jobWorkshopTimesheetsRetrieveOptions({ query }))

  const createMutation = useMutation(jobWorkshopTimesheetsCreateMutation())
  const updateMutation = useMutation(jobWorkshopTimesheetsPartialUpdateMutation())
  const deleteMutation = useMutation(jobWorkshopTimesheetsDestroyMutation())

  // Fable: Entries carry an accounting_date, so a write can move one off this
  // day — every settle invalidates the whole surface (the optionless key
  // partially matches every date's key) rather than only this day's.
  const invalidateDays = () =>
    void queryClient.invalidateQueries({ queryKey: jobWorkshopTimesheetsRetrieveQueryKey() })

  /** True on success; the caller closes the drawer only then. */
  const createEntry = async (body: WorkshopTimesheetEntryRequest): Promise<boolean> => {
    try {
      const location = sendLocation ? await phoneLocation() : null
      await createMutation.mutateAsync({ body: { ...body, location } })
    } catch (error) {
      report(error, 'The entry could not be saved.')
      return false
    }
    toast.success('Time saved.')
    invalidateDays()
    return true
  }

  const updateEntry = async (body: WorkshopTimesheetEntryUpdateRequest): Promise<boolean> => {
    try {
      const location = sendLocation ? await phoneLocation() : null
      await updateMutation.mutateAsync({ body: { ...body, location } })
    } catch (error) {
      report(error, 'The entry could not be updated.')
      return false
    }
    toast.success('Time saved.')
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
    toast.success('Entry deleted.')
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
