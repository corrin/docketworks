import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft } from 'lucide-react'

import { type ForecastMonthOut, salesForecastListOptions } from '@/api'
import { SummaryCard } from '@/features/shared/SummaryCard'
import { downloadCsv } from '@/lib/csv'
import { formatCurrency, formatPercentage, localIsoDate } from '@/lib/format'

import { SalesForecastDetailTable } from './SalesForecastDetailTable'
import { SalesForecastMonthTable } from './SalesForecastMonthTable'
import { varianceToneClass } from './variance'

interface ForecastSummary {
  xeroSales: number
  jmSales: number
  variance: number
  avgVariancePct: number
}

/**
 * The average is the mean of the monthly percentages, NOT a percentage of
 * the totals: a quiet month's drift matters as much as a busy one's, and
 * dividing the totals would let one large month bury eleven small ones.
 */
function summarise(months: readonly ForecastMonthOut[]): ForecastSummary | null {
  if (months.length === 0) return null
  return {
    xeroSales: months.reduce((total, month) => total + month.xero_sales, 0),
    jmSales: months.reduce((total, month) => total + month.jm_sales, 0),
    variance: months.reduce((total, month) => total + month.variance, 0),
    avgVariancePct: months.reduce((total, month) => total + month.variance_pct, 0) / months.length,
  }
}

function exportMonths(months: readonly ForecastMonthOut[]): void {
  downloadCsv(
    `sales-forecast-report-${localIsoDate()}.csv`,
    ['Month', 'Xero Sales', 'JM Sales', 'Variance', 'Variance %'],
    months.map((month) => [
      month.month_label,
      month.xero_sales.toFixed(2),
      month.jm_sales.toFixed(2),
      month.variance.toFixed(2),
      month.variance_pct.toFixed(1),
    ]),
  )
}

/**
 * Sales forecast: Xero invoice totals against Job Manager revenue
 * attribution, month by month, with a drill-down into the invoices and jobs
 * behind any one month. Both endpoints read restore-populated mirror tables,
 * so the page has no write path and nothing to invalidate.
 *
 * The page owns the month query and the selection; each table owns its own
 * markup, and the drill-down owns its own query (see
 * SalesForecastDetailTable).
 *
 * The name forecasts nothing: this reconciles two systems' accounts of
 * revenue that has already happened. It keeps v1's name anyway, because a
 * screen called the same thing in both repos is a screen whose numbers can
 * be compared while the port is being reconciled — and a rename would cost
 * that for the whole window in which it is most needed. Renaming is a
 * post-cutover sweep; see the engineering backlog in
 * docs/rewrite-status.md.
 */
export function SalesForecastPage() {
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null)

  const forecast = useQuery(salesForecastListOptions())
  const months = forecast.data?.months
  const summary = months === undefined ? null : summarise(months)
  const selected = months?.find((month) => month.month === selectedMonth) ?? null

  return (
    <div className="min-h-screen p-6">
      <div className="flex items-center justify-between">
        <h1
          className="text-xl font-bold text-gray-900"
          data-automation-id="SalesForecastReport-title"
        >
          Sales Forecast Report
        </h1>
        <div className="flex space-x-2">
          <button
            type="button"
            data-automation-id="SalesForecastReport-export"
            disabled={months === undefined || months.length === 0}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => {
              if (months !== undefined) exportMonths(months)
            }}
          >
            Export CSV
          </button>
          <button
            type="button"
            data-automation-id="SalesForecastReport-refresh"
            disabled={forecast.isFetching}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void forecast.refetch()}
          >
            Refresh
          </button>
        </div>
      </div>

      {selectedMonth === null ? (
        <SalesForecastMonthTable forecast={forecast} onSelect={setSelectedMonth}>
          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
            <p className="font-medium">About this report</p>
            <p>
              Compares Xero invoice totals against Job Manager revenue attribution by month, to
              surface unbilled work and invoicing patterns. Pick a month to see the invoices and
              jobs behind it.
            </p>
          </div>

          {summary !== null && (
            <div
              data-automation-id="SalesForecastReport-summary-cards"
              className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
            >
              <SummaryCard
                label="Total Xero Sales"
                valueAutomationId="SalesForecastReport-xero-sales-value"
              >
                {formatCurrency(summary.xeroSales)}
              </SummaryCard>
              <SummaryCard
                label="Total JM Sales"
                valueAutomationId="SalesForecastReport-jm-sales-value"
              >
                {formatCurrency(summary.jmSales)}
              </SummaryCard>
              <SummaryCard
                label="Total Variance"
                valueAutomationId="SalesForecastReport-variance-value"
              >
                <span className={varianceToneClass(summary.variance)}>
                  {formatCurrency(summary.variance)}
                </span>
              </SummaryCard>
              <SummaryCard
                label="Avg Variance %"
                valueAutomationId="SalesForecastReport-avg-variance-value"
              >
                <span className={varianceToneClass(summary.avgVariancePct)}>
                  {formatPercentage(summary.avgVariancePct)}
                </span>
              </SummaryCard>
            </div>
          )}
        </SalesForecastMonthTable>
      ) : (
        <>
          <div className="mt-4 flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <button
              type="button"
              data-automation-id="SalesForecastReport-back"
              className="cursor-pointer rounded-md p-1 hover:bg-gray-100"
              onClick={() => setSelectedMonth(null)}
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
            <div>
              <h2
                className="text-lg font-semibold text-gray-900"
                data-automation-id="SalesForecastReport-detail-month"
              >
                {selected?.month_label ?? selectedMonth}
              </h2>
              {selected !== null && (
                <div className="mt-1 flex gap-4 text-sm text-gray-600">
                  <span>Xero: {formatCurrency(selected.xero_sales)}</span>
                  <span>JM: {formatCurrency(selected.jm_sales)}</span>
                  <span className={`font-medium ${varianceToneClass(selected.variance)}`}>
                    Variance: {formatCurrency(selected.variance)} (
                    {formatPercentage(selected.variance_pct)})
                  </span>
                </div>
              )}
            </div>
          </div>

          <SalesForecastDetailTable month={selectedMonth} />
        </>
      )}
    </div>
  )
}
