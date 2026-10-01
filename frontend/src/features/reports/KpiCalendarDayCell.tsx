import type { KpiDayDataOut } from '@/api'
import { formatHoursDisplay } from '@/lib/format'
import { isoWeekday } from '@/lib/dates'

import {
  dayCategory,
  GRADE_WORDING,
  kpiToneClass,
  type KpiTarget,
  type MoneyFormatter,
} from './kpiDisplay'

interface KpiCalendarDayCellProps {
  day: KpiDayDataOut
  target: KpiTarget
  money: MoneyFormatter
  onSelect: (date: string) => void
}

/** Value then label, with a real space between them so the DOM text reads
    as the eye does ("$123 labour"): a text assertion or a screen reader
    sees one phrase, not "$123labour". */
function Line({ value, label }: { value: string; label: string }) {
  return (
    <span className="flex flex-wrap items-baseline gap-1">
      <span className="font-medium">{value}</span> <span className="text-gray-500">{label}</span>
    </span>
  )
}

/**
 * One day of the calendar. The three profit lines are the server's
 * `profit_breakdown`, not revenue less cost recomputed here: the day dialog
 * shows the same three numbers, and two subtractions can round apart.
 *
 * Placed in its weekday column by its own date (`gridColumnStart`), so a
 * missing day leaves a gap rather than shifting every later cell left,
 * which is what v1's positional padding did.
 *
 * A holiday shows only its gross profit (v1 parity).
 */
export function KpiCalendarDayCell({ day, target, money, onSelect }: KpiCalendarDayCellProps) {
  const category = dayCategory(day, target)
  const breakdown = day.details.profit_breakdown
  return (
    <button
      type="button"
      data-automation-id={`KpiCalendarReport-day-${day.date}`}
      data-category={category}
      // Fable: the E2E spec finds a day that billed hours by this attribute
      // rather than by parsing the cell's text for a non-zero hours figure.
      data-billable-hours={day.billable_hours}
      title={`${day.date}: ${GRADE_WORDING[category]}`}
      style={{ gridColumnStart: isoWeekday(day.date) }}
      className={`flex min-h-[7.5rem] flex-col rounded border p-2 text-left text-xs transition-shadow hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring ${kpiToneClass(category)}`}
      onClick={() => onSelect(day.date)}
    >
      <span className="mb-1 flex items-baseline justify-between">
        <span className="text-sm font-semibold">{day.day}</span>
        {day.holiday && <span className="font-medium text-gray-500">{day.holiday_name}</span>}
        <span className="sr-only">{GRADE_WORDING[category]}</span>
      </span>
      {!day.holiday && (
        <span className="flex flex-1 flex-col gap-0.5">
          <span className="flex flex-wrap items-baseline gap-1">
            <span className="font-medium">{formatHoursDisplay(day.billable_hours)}</span>{' '}
            <span className="text-gray-500">billable</span> <span className="text-gray-300">/</span>{' '}
            <span className="font-medium">{formatHoursDisplay(day.total_hours)}</span>{' '}
            <span className="text-gray-500">total</span>
          </span>
          <Line value={money(breakdown.labour_profit)} label="labour" />
          <Line value={money(breakdown.material_profit)} label="materials" />
          <Line value={money(breakdown.adjustment_profit)} label="adjustments" />
        </span>
      )}
      <span className="mt-0.5 flex flex-wrap items-baseline gap-1 border-t border-current/20 pt-1">
        <span
          className="text-sm font-semibold"
          data-automation-id={`KpiCalendarReport-day-${day.date}-gp`}
        >
          {money(day.gross_profit)}
        </span>{' '}
        <span className="text-gray-500">gross profit</span>
      </span>
    </button>
  )
}
