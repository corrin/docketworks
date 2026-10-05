import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobWorkshopTimesheetsCreateMutation,
  jobWorkshopTimesheetsDestroyMutation,
  jobWorkshopTimesheetsPartialUpdateMutation,
  jobWorkshopTimesheetsRetrieveOptions,
  jobWorkshopTimesheetsRetrieveQueryKey,
  timesheetsApprovalsRetrieveQueryKey,
  timesheetsMyDayBreaksCreateMutation,
  timesheetsMyDayBreaksDeleteMutation,
  timesheetsMyDayBreaksUpdateMutation,
  timesheetsMyDayClockMutation,
  timesheetsMyDaySubmitMutation,
  timesheetsMyDayTimesMutation,
} from '@/api'
import type {
  ClockTimesRequest,
  EntryLocationIn,
  FillRowIn,
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
 * The three entry writes behind the entry drawer, for the caller's own time
 * or, on Approve time, for the person the office is correcting.
 *
 * Fable: Writes settle before the UI moves on (the drawer stays open on
 * failure), so these are plain await-then-invalidate — the optimistic layer
 * useTimesheetEntries carries exists for a grid whose focus keeps moving,
 * which a modal drawer does not have. Every failure toasts: the E2E console
 * guard fails a spec on an unhandled console.error.
 *
 * `sendLocation` is whether a save carries the phone's location: only for
 * workshop staff of a company whose address is set, so nobody else is asked.
 * `ownerId` is whose time a new entry is, when it is not the caller's own.
 */
export function useWorkshopEntryWrites(sendLocation: boolean, ownerId?: string) {
  const queryClient = useQueryClient()
  const createMutation = useMutation(jobWorkshopTimesheetsCreateMutation())
  const updateMutation = useMutation(jobWorkshopTimesheetsPartialUpdateMutation())
  const deleteMutation = useMutation(jobWorkshopTimesheetsDestroyMutation())

  // Fable: Entries carry an accounting_date, so a write can move one off this
  // day — every settle invalidates the whole surface (the optionless key
  // partially matches every date's key) rather than only this day's. Approve
  // time reads the same entries, so it is refreshed with them.
  const invalidateDays = () => {
    void queryClient.invalidateQueries({ queryKey: jobWorkshopTimesheetsRetrieveQueryKey() })
    void queryClient.invalidateQueries({ queryKey: timesheetsApprovalsRetrieveQueryKey() })
  }

  /** True on success; the caller closes the drawer only then. */
  const createEntry = async (body: WorkshopTimesheetEntryRequest): Promise<boolean> => {
    try {
      const location = sendLocation ? await phoneLocation() : null
      await createMutation.mutateAsync({
        body: { ...body, location, ...(ownerId === undefined ? {} : { staff_id: ownerId }) },
      })
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
    createEntry,
    updateEntry,
    deleteEntry,
    saving: createMutation.isPending || updateMutation.isPending || deleteMutation.isPending,
  }
}

/**
 * Clock taps and hand-set clock times, for the caller's own day or, on
 * Approve time, the person the office is correcting (`ownerId`). True on
 * success; a refusal toasts the server's own words.
 */
export function useClocking(ownerId?: string) {
  const queryClient = useQueryClient()
  const clockMutation = useMutation(timesheetsMyDayClockMutation())
  const timesMutation = useMutation(timesheetsMyDayTimesMutation())

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: jobWorkshopTimesheetsRetrieveQueryKey() })
    void queryClient.invalidateQueries({ queryKey: timesheetsApprovalsRetrieveQueryKey() })
  }

  const clock = async (action: 'in' | 'out'): Promise<boolean> => {
    try {
      await clockMutation.mutateAsync({ body: { action } })
    } catch (error) {
      report(error, action === 'in' ? 'Clocking in failed.' : 'Clocking out failed.')
      return false
    }
    toast.success(action === 'in' ? 'Clocked in.' : 'Clocked out.')
    refresh()
    return true
  }

  const setTimes = async (body: Omit<ClockTimesRequest, 'staff_id'>): Promise<boolean> => {
    try {
      await timesMutation.mutateAsync({
        body: { ...body, ...(ownerId === undefined ? {} : { staff_id: ownerId }) },
      })
    } catch (error) {
      report(error, 'The clock times could not be saved.')
      return false
    }
    toast.success('Clock times saved.')
    refresh()
    return true
  }

  return { clock, setTimes, clocking: clockMutation.isPending || timesMutation.isPending }
}

/**
 * Adding, moving and removing a break, on the caller's own day or, on Approve
 * time, the day of the person the office is correcting (`ownerId`).
 */
export function useBreaks(ownerId?: string) {
  const queryClient = useQueryClient()
  const createMutation = useMutation(timesheetsMyDayBreaksCreateMutation())
  const updateMutation = useMutation(timesheetsMyDayBreaksUpdateMutation())
  const deleteMutation = useMutation(timesheetsMyDayBreaksDeleteMutation())

  const settle = async (write: Promise<unknown>, done: string, failed: string) => {
    try {
      await write
    } catch (error) {
      report(error, failed)
      return false
    }
    toast.success(done)
    void queryClient.invalidateQueries({ queryKey: jobWorkshopTimesheetsRetrieveQueryKey() })
    void queryClient.invalidateQueries({ queryKey: timesheetsApprovalsRetrieveQueryKey() })
    return true
  }

  return {
    addBreak: (date: string, start: string, end: string, paid: boolean) =>
      settle(
        createMutation.mutateAsync({
          body: { date, start, end, paid, ...(ownerId === undefined ? {} : { staff_id: ownerId }) },
        }),
        'Break added.',
        'The break could not be added.',
      ),
    changeBreak: (breakId: string, start: string, end: string) =>
      settle(
        updateMutation.mutateAsync({ path: { break_id: breakId }, body: { start, end } }),
        'Break saved.',
        'The break could not be saved.',
      ),
    removeBreak: (breakId: string) =>
      settle(
        deleteMutation.mutateAsync({ path: { break_id: breakId } }),
        'Break removed.',
        'The break could not be removed.',
      ),
    savingBreak: createMutation.isPending || updateMutation.isPending || deleteMutation.isPending,
  }
}

/**
 * Send a day to the office with the fill sheet's rows. The phone's position
 * goes with it for the same reason it goes with a single save: every entry
 * the rows become is judged by where it was sent from.
 */
export function useSubmitDay(sendLocation: boolean) {
  const queryClient = useQueryClient()
  const submitMutation = useMutation(timesheetsMyDaySubmitMutation())

  const submitDay = async (date: string, rows: FillRowIn[]): Promise<boolean> => {
    try {
      const location = sendLocation ? await phoneLocation() : null
      await submitMutation.mutateAsync({ body: { date, rows, location } })
    } catch (error) {
      report(error, 'The day could not be sent.')
      return false
    }
    toast.success('Day sent to the office.')
    void queryClient.invalidateQueries({ queryKey: jobWorkshopTimesheetsRetrieveQueryKey() })
    return true
  }

  return { submitDay, submitting: submitMutation.isPending }
}

/**
 * One staff member's own day on the workshop calendar: the day query plus the
 * three self-service writes. Server state lives in the TanStack cache only.
 */
export function useWorkshopDay(date: string, sendLocation: boolean) {
  const query = { date }
  const queryKey = jobWorkshopTimesheetsRetrieveQueryKey({ query })
  const dayQuery = useQuery(jobWorkshopTimesheetsRetrieveOptions({ query }))
  const writes = useWorkshopEntryWrites(sendLocation)

  return {
    dayQuery,
    refetch: () => void dayQuery.refetch(),
    ...writes,
    queryKey,
  }
}
