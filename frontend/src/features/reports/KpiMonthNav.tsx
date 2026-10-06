import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { isIsoMonthString, shiftMonth } from '@/lib/dates'
import { formatMonth, localIsoMonth } from '@/lib/format'

/** The earliest month the API accepts (apps/accounting/api.py bounds the year). */
const FIRST_MONTH = '2000-01'

interface KpiMonthNavProps {
  month: string
  onMonthChange: (month: string) => void
}

/**
 * Previous / pick / next / this month, the weekly timesheet's week nav
 * (features/timesheet/WeeklyOverviewPage.tsx) carried to months. v1 offered
 * a Select of the last ~25 months; the month input keeps "any past month"
 * reachable in one gesture while the arrows handle the common step.
 *
 * Future months are not navigable, as v1's selector did not offer them.
 * YYYY-MM compares as a string, which is how the bounds are checked.
 */
export function KpiMonthNav({ month, onMonthChange }: KpiMonthNavProps) {
  const thisMonth = localIsoMonth()
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      data-automation-id="KpiCalendarReport-month-nav"
    >
      <Button
        variant="outline"
        size="sm"
        aria-label="Previous month"
        disabled={month <= FIRST_MONTH}
        data-automation-id="KpiCalendarReport-prev"
        onClick={() => onMonthChange(shiftMonth(month, -1))}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <input
        type="month"
        value={month}
        min={FIRST_MONTH}
        max={thisMonth}
        aria-label="Month"
        className={`${INPUT_CLASS} w-auto`}
        data-automation-id="KpiCalendarReport-month-input"
        onChange={(event) => {
          const next = event.target.value
          // A cleared or half-typed input yields '' or an out-of-range month;
          // neither is a month to show.
          if (isIsoMonthString(next) && next <= thisMonth) onMonthChange(next)
        }}
      />
      <Button
        variant="outline"
        size="sm"
        aria-label="Next month"
        disabled={month >= thisMonth}
        data-automation-id="KpiCalendarReport-next"
        onClick={() => onMonthChange(shiftMonth(month, 1))}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={month === thisMonth}
        data-automation-id="KpiCalendarReport-this-month"
        onClick={() => onMonthChange(thisMonth)}
      >
        This month
      </Button>
      <span
        className="text-sm font-medium text-slate-700"
        data-automation-id="KpiCalendarReport-month-label"
      >
        {formatMonth(month)}
      </span>
    </div>
  )
}
