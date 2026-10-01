import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import {
  accountingReportsCalendarRetrieveOptions,
  type KpiCalendarResponse,
  type KpiDayDataOut,
} from '@/api'
import { QueryState } from '@/features/shared/QueryState'
import { SegmentedToggle } from '@/features/shared/SegmentedToggle'

import { KpiCalendarGrid } from './KpiCalendarGrid'
import { KpiDayDetailsDialog } from './KpiDayDetailsDialog'
import { KpiLabourDialog } from './KpiLabourDialog'
import { KpiMonthNav } from './KpiMonthNav'
import { KpiProfitDialog } from './KpiProfitDialog'
import { KpiStreamDialog } from './KpiStreamDialog'
import { KpiSummaryCards, type KpiCardDialog } from './KpiSummaryCards'
import { moneyFormatter, sortedDays, type KpiDecimals, type KpiTarget } from './kpiDisplay'
import type { KpiSearch } from './kpiSearch'

/**
 * Which breakdown is open, and over which month. A dialog shows one month's
 * figures, so it is open only while that month is the one on screen: the
 * month can change under it through the nav, the browser's back button or a
 * pasted URL, and holding the month here closes it on all three without an
 * effect to run after the fact.
 */
type OpenDialog = ({ kind: 'day'; date: string } | { kind: KpiCardDialog }) & { month: string }

export interface KpiCalendarPageProps {
  /** YYYY-MM; the route fills in this month. */
  month: string
  target: KpiTarget
  decimals: KpiDecimals
  /** Writes the setting into the URL; the route re-renders the page with it. */
  onSearchChange: (search: KpiSearch) => void
}

/** The day a cell was clicked on, which is a day of the month on screen. */
function dayOf(data: KpiCalendarResponse, date: string): KpiDayDataOut {
  const day = data.calendar_data[date]
  if (day === undefined) throw new Error(`No ${date} in the month on screen`)
  return day
}

/**
 * The KPI calendar: a month of day cells graded by billable hours or gross
 * profit, four summary cards, and a breakdown dialog behind each card and
 * each day.
 *
 * The frontend formats; it does not compute accounting. Every figure on
 * this page is a field of `monthly_totals`, a day's `details` or its
 * `profit_breakdown`. v1 summed `calendar_data` in the browser in four
 * places while its cards read the totals, and the two disagreed.
 *
 * The month, the ladder and the precision live in the URL (Xero's model), so
 * one month is one query key and changing month fires exactly one request —
 * v1 fired two per change (year then month) and raced them.
 */
export function KpiCalendarPage({ month, target, decimals, onSearchChange }: KpiCalendarPageProps) {
  const [opened, setOpened] = useState<OpenDialog | null>(null)
  const [yearPart, monthPart] = month.split('-')
  const report = useQuery({
    ...accountingReportsCalendarRetrieveOptions({
      query: { year: Number(yearPart), month: Number(monthPart) },
    }),
    // The previous month stays on screen, dimmed, while the next one loads:
    // a calendar that blanks on every step reads as broken, not busy.
    placeholderData: keepPreviousData,
  })
  const money = moneyFormatter(decimals)
  const data = report.data
  const days = data === undefined ? [] : sortedDays(data.calendar_data)
  // Closed while the data on screen is last month's placeholder: its dates
  // and totals are not this month's, whatever the URL says.
  const dialog =
    opened !== null && opened.month === month && !report.isPlaceholderData ? opened : null
  const open = (kind: KpiCardDialog) => setOpened({ kind, month })

  return (
    <div className="min-h-screen p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1
          className="text-xl font-bold text-gray-900"
          data-automation-id="KpiCalendarReport-title"
        >
          KPI Calendar
        </h1>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <span className="text-gray-500">Grade by</span>
          <SegmentedToggle
            value={target}
            options={[
              { value: 'hours', label: 'Billable hours' },
              { value: 'dollars', label: 'Gross profit' },
            ]}
            automationPrefix="KpiCalendarReport-target"
            onChange={(next) => onSearchChange({ target: next })}
          />
          <span className="text-gray-500">Show</span>
          <SegmentedToggle
            value={decimals}
            options={[
              { value: 0, label: 'Whole dollars' },
              { value: 2, label: 'Cents' },
            ]}
            automationPrefix="KpiCalendarReport-decimals"
            onChange={(next) => onSearchChange({ decimals: next })}
          />
          <button
            type="button"
            data-automation-id="KpiCalendarReport-refresh"
            disabled={report.isFetching}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void report.refetch()}
          >
            Refresh
          </button>
        </div>
      </div>
      <div className="mt-4">
        <KpiMonthNav month={month} onMonthChange={(next) => onSearchChange({ month: next })} />
      </div>

      <QueryState
        isPending={report.isPending}
        isError={report.isError}
        onRetry={() => void report.refetch()}
        loadingLabel="Loading KPI calendar..."
        loadingAutomationId="KpiCalendarReport-loading"
        errorLabel="Failed to load the KPI calendar."
      >
        {data !== undefined && (
          <div
            // Dimmed and inert while last month's figures stand in: a click
            // would open a dialog over them under this month's URL.
            className={report.isPlaceholderData ? 'pointer-events-none opacity-60' : ''}
            aria-busy={report.isPlaceholderData}
          >
            <KpiSummaryCards
              totals={data.monthly_totals}
              target={target}
              money={money}
              onOpen={open}
            />
            <KpiCalendarGrid
              days={days}
              weekendEnabled={data.weekend_enabled}
              target={target}
              money={money}
              onSelectDay={(date) => setOpened({ kind: 'day', date, month })}
            />
            <KpiDayDetailsDialog
              day={dialog?.kind === 'day' ? dayOf(data, dialog.date) : null}
              money={money}
              onClose={() => setOpened(null)}
            />
            <KpiLabourDialog
              open={dialog?.kind === 'labour'}
              month={month}
              totals={data.monthly_totals}
              days={days}
              money={money}
              onClose={() => setOpened(null)}
            />
            <KpiStreamDialog
              stream={
                dialog?.kind === 'material' || dialog?.kind === 'adjustment' ? dialog.kind : null
              }
              month={month}
              totals={data.monthly_totals}
              days={days}
              money={money}
              onClose={() => setOpened(null)}
            />
            <KpiProfitDialog
              open={dialog?.kind === 'profit'}
              month={month}
              totals={data.monthly_totals}
              thresholds={data.thresholds}
              money={money}
              onClose={() => setOpened(null)}
            />
          </div>
        )}
      </QueryState>
    </div>
  )
}
