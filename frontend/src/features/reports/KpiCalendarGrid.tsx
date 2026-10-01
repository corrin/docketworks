import type { KpiDayDataOut } from '@/api'

import { KpiCalendarDayCell } from './KpiCalendarDayCell'
import type { KpiTarget, MoneyFormatter } from './kpiDisplay'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const WEEKEND = ['Sat', 'Sun']

interface KpiCalendarGridProps {
  /** In date order — see sortedDays in kpiDisplay. */
  days: readonly KpiDayDataOut[]
  /** From the response, never from CompanyDefaults on a request of its own:
      the column count travels with the days it describes. */
  weekendEnabled: boolean
  target: KpiTarget
  money: MoneyFormatter
  onSelectDay: (date: string) => void
}

/**
 * Five or seven columns of day cells, Monday first. Each cell names its own
 * column, so the grid needs no leading padding and no trailing blanks: CSS
 * auto-placement starts a new row when a cell's column is behind the cursor.
 * v1 padded to a fixed 35 cells and always drew seven rows.
 */
export function KpiCalendarGrid({
  days,
  weekendEnabled,
  target,
  money,
  onSelectDay,
}: KpiCalendarGridProps) {
  const headers = weekendEnabled ? [...WEEKDAYS, ...WEEKEND] : WEEKDAYS
  return (
    // Fable: a wide grid scrolls inside its own container
    // (docs/design-language.md); v1 collapsed to one column on a phone, which
    // loses the week shape the tints are read across.
    <div className="mt-6 overflow-x-auto">
      <div
        className="grid min-w-[40rem] gap-1"
        style={{ gridTemplateColumns: `repeat(${headers.length}, minmax(0, 1fr))` }}
        data-automation-id="KpiCalendarReport-grid"
        data-columns={headers.length}
      >
        {headers.map((name) => (
          <div key={name} className="py-2 text-center text-xs font-semibold text-gray-500">
            {name}
          </div>
        ))}
        {days.map((day) => (
          <KpiCalendarDayCell
            key={day.date}
            day={day}
            target={target}
            money={money}
            onSelect={onSelectDay}
          />
        ))}
      </div>
    </div>
  )
}
