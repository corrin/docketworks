import { useState } from 'react'

import type { AttendanceOut, FillOut, PendingDayOut, StandardDayOut } from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { TOUCH_TARGET_CLASS } from '@/components/ui/touch'
import { formatDateLong } from '@/lib/format'

import { clockWords, fillWords, standardHoursWords } from './myTime'

interface ClockTimesFormProps {
  /** Prefix for the form's automation ids: the card's or the office row's. */
  automationId: string
  /** What the two fields open on, "HH:mm"; a blank finish is "not yet". */
  initialStart: string
  initialFinish: string
  /** A break always has a finish; a day at work does not yet. */
  finishRequired?: boolean
  saving: boolean
  onSave: (clockIn: string, clockOut: string | null) => Promise<boolean>
  onCancel: () => void
}

/**
 * A start and a finish set by hand: a day's clock times (a forgotten tap, a
 * correction, the office putting a day right) or a break's. For a day a blank
 * finish means the person is still at work. Shared by the worker's card, the
 * break sheet and Approve time, so there is one such form.
 */
export function ClockTimesForm({
  automationId,
  initialStart,
  initialFinish,
  finishRequired = false,
  saving,
  onSave,
  onCancel,
}: ClockTimesFormProps) {
  const [start, setStart] = useState(initialStart)
  const [finish, setFinish] = useState(initialFinish)

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      data-automation-id={`${automationId}-times-form`}
      onSubmit={(event) => {
        event.preventDefault()
        void onSave(`${start}:00`, finish === '' ? null : `${finish}:00`).then((saved) => {
          if (saved) onCancel()
        })
      }}
    >
      <label className="text-sm font-medium text-gray-700">
        Started
        <input
          type="time"
          required
          value={start}
          className={`mt-1 block ${INPUT_CLASS}`}
          data-automation-id={`${automationId}-start`}
          onChange={(event) => setStart(event.target.value)}
        />
      </label>
      <label className="text-sm font-medium text-gray-700">
        Finished
        <input
          type="time"
          required={finishRequired}
          value={finish}
          className={`mt-1 block ${INPUT_CLASS}`}
          data-automation-id={`${automationId}-finish`}
          onChange={(event) => setFinish(event.target.value)}
        />
      </label>
      <Button
        type="submit"
        className={TOUCH_TARGET_CLASS}
        disabled={saving || start === ''}
        data-automation-id={`${automationId}-times-save`}
      >
        Save times
      </Button>
      <Button
        type="button"
        variant="outline"
        className={TOUCH_TARGET_CLASS}
        disabled={saving}
        onClick={onCancel}
      >
        Cancel
      </Button>
    </form>
  )
}

interface DayCardProps {
  /** The day shown, YYYY-MM-DD. */
  date: string
  /** Whether that day is today: only today is clocked by a tap. */
  isToday: boolean
  day: AttendanceOut
  /** Hours to fill, entered and to go, from the server; null until the day
      has both clock times. */
  fill: FillOut | null
  /** An earlier day he clocked and has not sent, and how far it got. */
  pending: PendingDayOut | null
  /** The company's standard hours for the day; null on a weekend. */
  standard: StandardDayOut | null
  /** The standard finish to offer when this earlier day was left clocked in. */
  missedClockOutFinish: string | null
  clocking: boolean
  onClock: (action: 'in' | 'out') => Promise<boolean>
  onSetTimes: (clockIn: string, clockOut: string | null) => Promise<boolean>
  onOpenDay: (date: string) => void
  onFill: () => void
  /** Record the standard hours as the day's times, then fill it. */
  onUseStandardHours: () => void
  onAddBreak: () => void
}

/** What stands in for the fill figures on a day that has none yet. */
function noFillWords(day: AttendanceOut, standard: StandardDayOut | null): string {
  // Nobody clocked: the standard day is what it falls back to.
  if (day.state === 'not_clocked_in') return standardHoursWords(standard)
  return 'Clock out to see what is left to fill.'
}

/**
 * The top of My time: where the day stands and the one thing to do next.
 * A tap clocks today in or out at the server's time; any day's times can be
 * set by hand, which is also how a forgotten tap is made good.
 */
export function DayCard({
  date,
  isToday,
  day,
  fill,
  pending,
  standard,
  missedClockOutFinish,
  clocking,
  onClock,
  onSetTimes,
  onOpenDay,
  onFill,
  onUseStandardHours,
  onAddBreak,
}: DayCardProps) {
  const [editingTimes, setEditingTimes] = useState(false)
  const clockIn = day.clock_in

  return (
    <div
      className="space-y-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      data-automation-id="DayCard"
    >
      {pending !== null && pending.date !== date && (
        <p
          className="rounded bg-amber-50 p-2 text-sm text-amber-900"
          data-automation-id="DayCard-pending"
        >
          {formatDateLong(pending.date)}{' '}
          {pending.state === 'at_work' ? 'is still clocked in.' : 'has not been sent.'}{' '}
          <button
            type="button"
            className="font-medium underline underline-offset-2"
            data-automation-id="DayCard-pending-open"
            onClick={() => onOpenDay(pending.date)}
          >
            {pending.state === 'at_work' ? 'Set the finish time' : 'Finish it'}
          </button>
        </p>
      )}
      <p className="text-lg font-semibold text-gray-900" data-automation-id="DayCard-state">
        {clockWords(day)}
      </p>
      <p className="text-sm text-gray-700" data-automation-id="DayCard-fill">
        {fill === null ? noFillWords(day, standard) : fillWords(fill)}
      </p>
      {/* He is told what the office is told about how his day was clocked. */}
      {day.cautions.length > 0 && (
        <p className="text-sm font-medium text-amber-800" data-automation-id="DayCard-cautions">
          {day.cautions.join(' · ')}
        </p>
      )}
      {missedClockOutFinish !== null && clockIn !== null && !editingTimes && (
        <p className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          No clock out.{' '}
          <button
            type="button"
            className="font-medium underline underline-offset-2"
            disabled={clocking}
            data-automation-id="DayCard-use-standard-finish"
            onClick={() => void onSetTimes(clockIn, missedClockOutFinish)}
          >
            Use {missedClockOutFinish.slice(0, 5)}?
          </button>
        </p>
      )}
      {editingTimes ? (
        <ClockTimesForm
          automationId="DayCard"
          // A day nobody clocked opens on the standard hours, both of them;
          // a day at work keeps its finish blank, since he is still there.
          initialStart={day.clock_in?.slice(0, 5) ?? standard?.start.slice(0, 5) ?? ''}
          initialFinish={
            day.clock_out?.slice(0, 5) ??
            (day.clock_in === null ? (standard?.end.slice(0, 5) ?? '') : '')
          }
          saving={clocking}
          onSave={onSetTimes}
          onCancel={() => setEditingTimes(false)}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {isToday && day.state === 'not_clocked_in' && (
            <Button
              className={TOUCH_TARGET_CLASS}
              disabled={clocking}
              data-automation-id="DayCard-clock-in"
              onClick={() => void onClock('in')}
            >
              Clock in
            </Button>
          )}
          {isToday && day.state === 'at_work' && (
            <Button
              className={TOUCH_TARGET_CLASS}
              disabled={clocking}
              data-automation-id="DayCard-clock-out"
              onClick={() => void onClock('out')}
            >
              Clock out
            </Button>
          )}
          {/* Clocked out, or never clocked on a day with standard hours: on the
              second, the tap records the standard hours first. */}
          {(day.state === 'clocked_out' ||
            (day.state === 'not_clocked_in' && standard !== null)) && (
            <Button
              className={TOUCH_TARGET_CLASS}
              variant={isToday && day.state === 'not_clocked_in' ? 'outline' : 'default'}
              disabled={clocking}
              data-automation-id="DayCard-fill-and-send"
              onClick={day.state === 'clocked_out' ? onFill : onUseStandardHours}
            >
              Fill and send
            </Button>
          )}
          {/* Reopening is its own control: a stray tap on Clock in never does it. */}
          {day.state === 'clocked_out' && clockIn !== null && (
            <Button
              variant="outline"
              className={TOUCH_TARGET_CLASS}
              disabled={clocking}
              data-automation-id="DayCard-clock-back-in"
              onClick={() => void onSetTimes(clockIn, null)}
            >
              Clock back in
            </Button>
          )}
          <Button
            variant="outline"
            className={TOUCH_TARGET_CLASS}
            disabled={clocking}
            data-automation-id="DayCard-change-times"
            onClick={() => setEditingTimes(true)}
          >
            {day.state === 'not_clocked_in' ? 'Set times' : 'Change times'}
          </Button>
          {/* A break belongs to a day that has clock times. */}
          {day.state !== 'not_clocked_in' && (
            <Button
              variant="outline"
              className={TOUCH_TARGET_CLASS}
              disabled={clocking}
              data-automation-id="DayCard-add-break"
              onClick={onAddBreak}
            >
              Add a break
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
