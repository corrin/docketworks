import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { timesheetsMyDayPlacementOptions } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatHoursDisplay } from '@/lib/format'

/** The ordinary pay rate: only time at it is asked about. */
export const ORDINARY_RATE = 1

/** A new entry's hours, its day, whose it is and its job: what the server places. */
export type OvertimeQuestion = Parameters<typeof timesheetsMyDayPlacementOptions>[0]['query']

interface UseOvertimeAskOptions {
  confirmLabel: string
  /** Prefix for the dialog's automation ids: `-overtime`, `-overtime-cancel`, `-overtime-save`. */
  automationPrefix: string
  /** Whose time it is, when someone else enters it: the office grid names the person. */
  whose?: string
}

/**
 * The one overtime question. Before new time at the ordinary rate saves, he is
 * told how many of its hours go past his usual day as time and a half. Marking
 * overtime is his to do (owner, 2026-10-24 and 2026-10-26), and the question is
 * the same whoever enters the time (owner, 2026-11-02). So the office grid, the
 * entry drawer and the fill sheet all ask it here.
 *
 * `ask` resolves true to save and false when he cancels. `askFor` gets the
 * hours from the server first. Its fetch error reaches the caller.
 */
export function useOvertimeAsk({ confirmLabel, automationPrefix, whose }: UseOvertimeAskOptions) {
  const { t } = useTranslation('timesheet')
  const queryClient = useQueryClient()
  const [pending, setPending] = useState<{
    hours: number
    answer: (save: boolean) => void
  } | null>(null)

  const ask = (overtimeHours: number): Promise<boolean> =>
    overtimeHours > 0
      ? new Promise((answer) => setPending({ hours: overtimeHours, answer }))
      : Promise.resolve(true)

  const askFor = async (question: OvertimeQuestion): Promise<boolean> => {
    const placed = await queryClient.fetchQuery(
      timesheetsMyDayPlacementOptions({ query: question }),
    )
    return ask(placed.overtime_hours)
  }

  const settle = (save: boolean) => {
    pending?.answer(save)
    setPending(null)
  }

  const dialog = (
    <Dialog
      open={pending !== null}
      onOpenChange={(open) => {
        if (!open) settle(false)
      }}
    >
      <DialogContent className="sm:max-w-md" data-automation-id={`${automationPrefix}-overtime`}>
        <DialogHeader>
          <DialogTitle>
            {whose === undefined
              ? t('entryDrawer.overtime.title')
              : t('entryDrawer.overtime.titleFor', { name: whose })}
          </DialogTitle>
          <DialogDescription>
            {pending !== null &&
              (whose === undefined
                ? t('entryDrawer.overtime.body', { hours: formatHoursDisplay(pending.hours) })
                : t('entryDrawer.overtime.bodyFor', {
                    hours: formatHoursDisplay(pending.hours),
                    name: whose,
                  }))}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="ghost"
            data-automation-id={`${automationPrefix}-overtime-cancel`}
            onClick={() => settle(false)}
          >
            {t('entryDrawer.cancel')}
          </Button>
          <Button
            data-automation-id={`${automationPrefix}-overtime-save`}
            onClick={() => settle(true)}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )

  return { ask, askFor, dialog }
}
