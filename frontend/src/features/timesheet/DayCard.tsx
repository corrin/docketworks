import { useState } from 'react'

import type { AttendanceOut, FillOut, PendingDayOut } from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { TOUCH_TARGET_CLASS } from '@/components/ui/touch'
import { formatDateLong } from '@/lib/format'

import { clockWords, fillWords } from './myTime'

interface ClockTimesFormProps {
  /** Prefix for the form's automation ids: the card's or the office row's. */
  automationId: string
  day: AttendanceOut
  /** What the start field offers when the day has no clock-in yet, "HH:mm". */
  defaultStart: string
  saving: boolean
  onSave: (clockIn: string, clockOut: string | null) => Promise<boolean>
  onCancel: () => void
}

/**
 * Clock times set by hand: a forgotten tap, a correction, or the office
 * putting a day right. A blank finish means the person is still at work.
 * Shared by the worker's card and Approve time, so there is one such form.
 */
export function ClockTimesForm({
  automationId,
  day,
  defaultStart,
  saving,
  onSave,
  onCancel,
}: ClockTimesFormProps) {
  const [start, setStart] = useState(day.clock_in?.slice(0, 5) ?? defaultStart)
  const [finish, setFinish] = useState(day.clock_out?.slice(0, 5) ?? '')

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
  dayStart: string
  clocking: boolean
  onClock: (action: 'in' | 'out') => Promise<boolean>
  onSetTimes: (clockIn: string, clockOut: string | null) => Promise<boolean>
  onOpenDay: (date: string) => void
  onFill: () => void
}

/** What stands in for the fill figures on a day that has none yet. */
function noFillWords(day: AttendanceOut): string {
  return day.state === 'not_clocked_in'
    ? 'Clock times not set.'
    : 'Clock out to see what is left to fill.'
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
  dayStart,
  clocking,
  onClock,
  onSetTimes,
  onOpenDay,
  onFill,
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
        {fill === null ? noFillWords(day) : fillWords(fill)}
      </p>
      {editingTimes ? (
        <ClockTimesForm
          automationId="DayCard"
          day={day}
          defaultStart={dayStart}
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
          {day.state === 'clocked_out' && (
            <Button
              className={TOUCH_TARGET_CLASS}
              disabled={clocking}
              data-automation-id="DayCard-fill-and-send"
              onClick={onFill}
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
        </div>
      )}
    </div>
  )
}
