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

/** What a sweep did, in words: the hours moved, then each day it left alone. */
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
  return skipped.length === 0
    ? moved
    : i18n.t('timesheet:sweep.withSkipped', { moved, skipped: skipped.join(', ') })
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
    toast.success(sweepWords(result))
    void queryClient.invalidateQueries({ queryKey: timesheetsApprovalsRetrieveQueryKey() })
    void queryClient.invalidateQueries({ queryKey: timesheetsWeeklyRetrieveQueryKey() })
  }

  return { sweep, sweeping: mutation.isPending }
}
