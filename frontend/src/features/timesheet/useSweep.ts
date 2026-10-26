import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  timesheetsApprovalsRetrieveQueryKey,
  timesheetsApprovalsSweepMutation,
  timesheetsWeeklyRetrieveQueryKey,
} from '@/api'
import type { SweepIn, SweepOut, SweepSkipOut } from '@/api'
import { formatDate, formatHoursDisplay } from '@/lib/format'
import { i18n } from '@/lib/i18n'

const SKIP_KEYS = {
  still_clocked_in: 'stillClockedIn',
  no_clock_times: 'noClockTimes',
} as const satisfies Record<SweepSkipOut['reason'], string>

/** What a sweep did, in words: the hours moved, each day it left alone, then
    each person it took past the usual day (the server words those). */
export function sweepWords(result: SweepOut): string {
  const moved = i18n.t('timesheet:sweep.moved', {
    hours: formatHoursDisplay(result.swept_hours),
  })
  const skipped = result.skipped.map((skip) =>
    i18n.t('timesheet:sweep.skippedDay', {
      name: skip.staff_name,
      date: formatDate(skip.date),
      reason: i18n.t(`timesheet:sweep.skip.${SKIP_KEYS[skip.reason]}`),
    }),
  )
  const words =
    skipped.length === 0
      ? moved
      : i18n.t('timesheet:sweep.withSkipped', { moved, skipped: skipped.join(', ') })
  return result.overtime.length === 0
    ? words
    : i18n.t('timesheet:sweep.withOvertime', {
        words,
        overtime: result.overtime.map((each) => each.message).join(' '),
      })
}

/**
 * The office's sweep (KAN-380): clocked time on no job goes onto General
 * work and the days are approved. One person's day, everyone's day and
 * everyone's week all call this, so they report alike.
 */
export function useSweep() {
  const queryClient = useQueryClient()
  const mutation = useMutation(timesheetsApprovalsSweepMutation())

  const sweep = async (body: SweepIn, failure: string) => {
    let result: SweepOut
    try {
      result = await mutation.mutateAsync({ body })
    } catch (error) {
      toast.error(apiErrorMessage(error, failure))
      return
    }
    // Overtime the sweep booked is the office's to check (owner, 2026-10-25).
    if (result.overtime.length === 0) toast.success(sweepWords(result))
    else toast.warning(sweepWords(result))
    void queryClient.invalidateQueries({ queryKey: timesheetsApprovalsRetrieveQueryKey() })
    void queryClient.invalidateQueries({ queryKey: timesheetsWeeklyRetrieveQueryKey() })
  }

  return { sweep, sweeping: mutation.isPending }
}
