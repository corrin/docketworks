import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
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
  timesheetsMyDayStandardHoursMutation,
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
// looking dead.
const LOCATION_TIMEOUT_MS = 5000
// How old a fix may be and still vouch for a write. A minute is less than the
// walk from the workshop to anywhere it would mislead about, and it lets a tap
// answer at once instead of waiting on the GPS; anything older is read fresh.
const LOCATION_MAX_AGE_MS = 60_000

/**
 * The latest fix while My time is open, from watching the position: a phone
 * that moves is seen at once. The browser's own cache was not enough: asked
 * for a fix up to a minute old, it answered with where the phone had been
 * rather than where it had just arrived.
 */
let watchedFix: { location: EntryLocationIn; at: number } | null = null

function readFresh(): Promise<EntryLocationIn | null> {
  if (!('geolocation' in navigator)) return Promise.resolve(null)
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      ({ coords, timestamp }) => {
        const location = { latitude: coords.latitude, longitude: coords.longitude }
        watchedFix = { location, at: timestamp }
        resolve(location)
      },
      () => resolve(null),
      { timeout: LOCATION_TIMEOUT_MS, maximumAge: 0 },
    )
  })
}

/** Whether location is allowed, or null where the phone cannot say (no
    Permissions API, or one that will not answer for geolocation). */
function locationPermission(): Promise<PermissionState | null> {
  if (!('permissions' in navigator)) return Promise.resolve(null)
  return navigator.permissions.query({ name: 'geolocation' }).then(
    (status) => status.state,
    // deliberate-swallow: older iOS Safari and some WebViews refuse the query
    // for geolocation; the write then reads its position fresh.
    () => null,
  )
}

/**
 * Where the phone says it is, or null when it will not say: location refused,
 * no fix in time, or no position service. The server marks a worker's save
 * that arrives without a location at the company address, so null is an
 * answer, not a failure, and the save goes ahead either way. A watched fix is
 * used only while location is known to be allowed: one taken before he turned
 * it off must not vouch for a write made after.
 */
async function lookUpLocation(): Promise<EntryLocationIn | null> {
  const permission = await locationPermission()
  if (permission !== 'granted') {
    watchedFix = null
    return readFresh()
  }
  if (watchedFix !== null && Date.now() - watchedFix.at <= LOCATION_MAX_AGE_MS) {
    return watchedFix.location
  }
  return readFresh()
}

// The longest a write waits on the phone before going ahead without a
// location: the fresh read's own timeout, and a little for the permission.
export const LOCATION_LOOKUP_LIMIT_MS = 8000

/** The phone's position for a write, never a failed write: anything the
    phone throws, and any wait past the limit, is "no location". */
export function phoneLocation(): Promise<EntryLocationIn | null> {
  return Promise.race([
    // deliberate-swallow: a phone that throws while asked is a phone that
    // gave no location, which the server marks; the write goes ahead.
    lookUpLocation().catch(() => null),
    new Promise<null>((resolve) => {
      setTimeout(() => resolve(null), LOCATION_LOOKUP_LIMIT_MS)
    }),
  ])
}

/**
 * Ask for the phone's position as My time opens, so the permission prompt
 * comes with the page and not on his first tap, and keep the latest fix while
 * the page is open.
 */
export function useAskForLocation(ask: boolean): void {
  useEffect(() => {
    if (!ask || !('geolocation' in navigator)) return undefined
    const watch = navigator.geolocation.watchPosition(
      ({ coords, timestamp }) => {
        watchedFix = {
          location: { latitude: coords.latitude, longitude: coords.longitude },
          at: timestamp,
        }
      },
      () => {
        // deliberate-swallow: refused or no fix; each write then reads fresh
        // and sends none, which the server marks.
        watchedFix = null
      },
      { maximumAge: 0 },
    )
    return () => {
      navigator.geolocation.clearWatch(watch)
      watchedFix = null
    }
  }, [ask])
}

/** The location a write carries: the phone's, when this user's writes are judged by it. */
function writeLocation(sendLocation: boolean): Promise<EntryLocationIn | null> {
  return sendLocation ? phoneLocation() : Promise.resolve(null)
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
      const location = await writeLocation(sendLocation)
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
      const location = await writeLocation(sendLocation)
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
      const location = await writeLocation(sendLocation)
      await deleteMutation.mutateAsync({ query: { entry_id: entryId, ...location } })
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
export function useClocking(sendLocation: boolean, ownerId?: string) {
  const queryClient = useQueryClient()
  const clockMutation = useMutation(timesheetsMyDayClockMutation())
  const timesMutation = useMutation(timesheetsMyDayTimesMutation())
  const standardMutation = useMutation(timesheetsMyDayStandardHoursMutation())

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: jobWorkshopTimesheetsRetrieveQueryKey() })
    void queryClient.invalidateQueries({ queryKey: timesheetsApprovalsRetrieveQueryKey() })
  }

  const clock = async (action: 'in' | 'out'): Promise<boolean> => {
    try {
      const location = await writeLocation(sendLocation)
      await clockMutation.mutateAsync({ body: { action, location } })
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
      const location = await writeLocation(sendLocation)
      await timesMutation.mutateAsync({
        body: { ...body, location, ...(ownerId === undefined ? {} : { staff_id: ownerId }) },
      })
    } catch (error) {
      report(error, 'The clock times could not be saved.')
      return false
    }
    toast.success('Clock times saved.')
    refresh()
    return true
  }

  /** He forgot to clock: record the company's standard hours as the day's times. */
  const recordStandardHours = async (date: string): Promise<boolean> => {
    try {
      const location = await writeLocation(sendLocation)
      await standardMutation.mutateAsync({
        body: { date, location, ...(ownerId === undefined ? {} : { staff_id: ownerId }) },
      })
    } catch (error) {
      report(error, 'The standard hours could not be recorded.')
      return false
    }
    refresh()
    return true
  }

  return {
    clock,
    setTimes,
    recordStandardHours,
    clocking: clockMutation.isPending || timesMutation.isPending || standardMutation.isPending,
  }
}

/**
 * Adding, moving and removing a break, on the caller's own day or, on Approve
 * time, the day of the person the office is correcting (`ownerId`).
 */
export function useBreaks(sendLocation: boolean, ownerId?: string) {
  const queryClient = useQueryClient()
  const createMutation = useMutation(timesheetsMyDayBreaksCreateMutation())
  const updateMutation = useMutation(timesheetsMyDayBreaksUpdateMutation())
  const deleteMutation = useMutation(timesheetsMyDayBreaksDeleteMutation())

  const settle = async (
    write: (location: EntryLocationIn | null) => Promise<unknown>,
    done: string,
    failed: string,
  ) => {
    try {
      await write(await writeLocation(sendLocation))
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
        (location) =>
          createMutation.mutateAsync({
            body: {
              date,
              start,
              end,
              paid,
              location,
              ...(ownerId === undefined ? {} : { staff_id: ownerId }),
            },
          }),
        'Break added.',
        'The break could not be added.',
      ),
    changeBreak: (breakId: string, start: string, end: string) =>
      settle(
        (location) =>
          updateMutation.mutateAsync({
            path: { break_id: breakId },
            body: { start, end, location },
          }),
        'Break saved.',
        'The break could not be saved.',
      ),
    removeBreak: (breakId: string) =>
      settle(
        (location) =>
          deleteMutation.mutateAsync({ path: { break_id: breakId }, query: { ...location } }),
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
      const location = await writeLocation(sendLocation)
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
