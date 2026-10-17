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

const SKIP_WORDS: Record<SweepSkipOut['reason'], string> = {
  still_clocked_in: 'still clocked in',
  no_clock_times: 'no clock times',
}

/** What a sweep did, in words: the hours moved, then each day it left alone. */
export function sweepWords(result: SweepOut): string {
  const moved = `${formatHoursDisplay(result.swept_hours)} put on General work.`
  const skipped = result.skipped.map(
    (skip) => `${skip.staff_name} on ${formatDate(skip.date)} (${SKIP_WORDS[skip.reason]})`,
  )
  return skipped.length === 0 ? moved : `${moved} Not swept: ${skipped.join(', ')}.`
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
