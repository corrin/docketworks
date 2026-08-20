import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronLeft } from 'lucide-react'

import {
  type ForecastComparisonRowOut,
  type ForecastMonthOut,
  salesForecastListOptions,
  salesForecastMonthDetailOptions,
} from '@/api'
import { ListTable } from '@/features/shared/ListTable'
import { SortHeader } from '@/features/shared/SortHeader'
import { SummaryCard } from '@/features/shared/SummaryCard'
import { type SortDir, useSortState } from '@/features/shared/useSortState'
import { downloadCsv } from '@/lib/csv'
import { formatCurrency, formatDate, formatPercentage, localIsoDate } from '@/lib/format'

/** Variance bands, in percentage points (ADR 0046): the report exists to make
    a month that drifted from Xero visible at a glance, so the badge colour is
    the answer and the number is the evidence. */
const CLOSE_ENOUGH_PCT = 10
const WORTH_A_LOOK_PCT = 25

type DetailColumn = keyof Pick<
  ForecastComparisonRowOut,
  | 'job_start_date'
  | 'date'
  | 'company_name'
  | 'invoice_numbers'
  | 'job_number'
  | 'note'
  | 'total_invoiced'
  | 'job_revenue'
  | 'variance'
  | 'variance_all_time'
>

function varianceBadgeClass(variancePct: number): string {
  const drift = Math.abs(variancePct)
  if (drift < CLOSE_ENOUGH_PCT) return 'bg-green-100 text-green-800'
  if (drift < WORTH_A_LOOK_PCT) return 'bg-yellow-100 text-yellow-800'
  return 'bg-red-100 text-red-800'
}

function varianceToneClass(variance: number): string {
  return variance >= 0 ? 'text-green-600' : 'text-red-600'
}

/**
 * Nulls sort last in BOTH directions, rather than v1's "whichever end the
 * direction puts them". Reversing a sort to see the other extreme otherwise
 * lands you on a screenful of em dashes, which is never the row anyone
 * reversed the sort to find.
 */
function compareRows(
  left: ForecastComparisonRowOut,
  right: ForecastComparisonRowOut,
  column: DetailColumn,
  dir: SortDir,
): number {
  const a = left[column]
  const b = right[column]
  if (a === null) return b === null ? 0 : 1
  if (b === null) return -1

  const sign = dir === 'asc' ? 1 : -1
  if (typeof a === 'string' && typeof b === 'string') return a.localeCompare(b) * sign
  if (typeof a === 'number' && typeof b === 'number') return (a - b) * sign
  return 0
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

/** An optional money cell: a true zero here means "no invoice" and "no
    revenue", which an em dash says and $0.00 does not. */
function MoneyCell({ value }: { value: number }) {
  return value > 0 ? <>{formatCurrency(value)}</> : <span className="text-gray-400">—</span>
}

function OptionalCell({ value }: { value: string | null }) {
  return value === null ? <span className="text-gray-400">—</span> : <>{value}</>
}

/**
 * Sales forecast: Xero invoice totals against Job Manager revenue
 * attribution, by month, with a drill-down into the invoices and jobs behind
 * any one month. Both endpoints read restore-populated mirror tables, so the
 * page has no write path and nothing to invalidate.
 */
export function SalesForecastPage() {
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null)
  const detailSort = useSortState<DetailColumn>('date')

  const forecast = useQuery(salesForecastListOptions())
  const detail = useQuery({
    ...salesForecastMonthDetailOptions({ path: { month: selectedMonth ?? '' } }),
    enabled: selectedMonth !== null,
  })

  const months = forecast.data?.months
  const selected = months?.find((month) => month.month === selectedMonth) ?? null
  const summary =
    months === undefined || months.length === 0
      ? null
      : {
          xeroSales: months.reduce((total, month) => total + month.xero_sales, 0),
          jmSales: months.reduce((total, month) => total + month.jm_sales, 0),
          variance: months.reduce((total, month) => total + month.variance, 0),
          avgVariancePct:
            months.reduce((total, month) => total + month.variance_pct, 0) / months.length,
        }

  const detailRows =
    detail.data === undefined
      ? undefined
      : detail.data.rows.toSorted((left, right) =>
          compareRows(left, right, detailSort.sortBy, detailSort.sortDir),
        )

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
        <ListTable
          isPending={forecast.isPending}
          isError={forecast.isError}
          onRetry={() => void forecast.refetch()}
          loadingLabel="Loading sales forecast..."
          loadingAutomationId="SalesForecastReport-loading"
          errorLabel="Failed to load the sales forecast."
          rows={months}
          emptyLabel="No sales data available"
          automationId="SalesForecastReport-table"
          head={
            <tr className="border-b border-gray-200 text-gray-500">
              <th scope="col" className="px-3 py-2 text-left">
                Month
              </th>
              <th scope="col" className="px-3 py-2 text-right">
                Xero Sales
              </th>
              <th scope="col" className="px-3 py-2 text-right">
                JM Sales
              </th>
              <th scope="col" className="px-3 py-2 text-right">
                Variance
              </th>
              <th scope="col" className="px-3 py-2 text-right">
                Variance %
              </th>
            </tr>
          }
          renderRow={(month) => (
            <tr
              key={month.month}
              data-automation-id={`SalesForecastReport-month-${month.month}`}
              className="cursor-pointer border-b border-gray-100 hover:bg-blue-50"
              onClick={() => setSelectedMonth(month.month)}
            >
              <td className="px-3 py-2 font-medium text-gray-900">{month.month_label}</td>
              <td className="px-3 py-2 text-right">{formatCurrency(month.xero_sales)}</td>
              <td className="px-3 py-2 text-right">{formatCurrency(month.jm_sales)}</td>
              <td
                className={`px-3 py-2 text-right font-medium ${varianceToneClass(month.variance)}`}
              >
                {formatCurrency(month.variance)}
              </td>
              <td className="px-3 py-2 text-right">
                <span
                  className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${varianceBadgeClass(
                    month.variance_pct,
                  )}`}
                >
                  {formatPercentage(month.variance_pct)}
                </span>
              </td>
            </tr>
          )}
        >
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
        </ListTable>
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

          <ListTable
            isPending={detail.isPending}
            isError={detail.isError}
            onRetry={() => void detail.refetch()}
            loadingLabel="Loading month details..."
            loadingAutomationId="SalesForecastReport-detail-loading"
            errorLabel="Failed to load the month details."
            rows={detailRows}
            emptyLabel="No invoice or job data for this month"
            automationId="SalesForecastReport-detail-table"
            head={
              <tr className="border-b border-gray-200 text-gray-500">
                <SortHeader
                  column="job_start_date"
                  label="Job Start"
                  automationId="SalesForecastReport-header-job-start"
                  align="left"
                  {...detailSort}
                />
                <SortHeader
                  column="date"
                  label="Job Finish"
                  automationId="SalesForecastReport-header-job-finish"
                  align="left"
                  {...detailSort}
                />
                <SortHeader
                  column="company_name"
                  label="Company"
                  automationId="SalesForecastReport-header-company"
                  align="left"
                  {...detailSort}
                />
                <SortHeader
                  column="invoice_numbers"
                  label="Invoices"
                  automationId="SalesForecastReport-header-invoices"
                  align="left"
                  {...detailSort}
                />
                <SortHeader
                  column="job_number"
                  label="Job"
                  automationId="SalesForecastReport-header-job"
                  align="left"
                  {...detailSort}
                />
                <SortHeader
                  column="note"
                  label="Note"
                  automationId="SalesForecastReport-header-note"
                  align="left"
                  {...detailSort}
                />
                <SortHeader
                  column="total_invoiced"
                  label="Xero Revenue"
                  automationId="SalesForecastReport-header-xero-revenue"
                  align="right"
                  {...detailSort}
                />
                <SortHeader
                  column="job_revenue"
                  label="JM Revenue"
                  automationId="SalesForecastReport-header-jm-revenue"
                  align="right"
                  {...detailSort}
                />
                <SortHeader
                  column="variance"
                  label="Variance"
                  automationId="SalesForecastReport-header-variance"
                  align="right"
                  {...detailSort}
                />
                <SortHeader
                  column="variance_all_time"
                  label="All-Time Delta"
                  automationId="SalesForecastReport-header-all-time"
                  align="right"
                  {...detailSort}
                />
              </tr>
            }
            renderRow={(row) => (
              <tr
                // Rows are one Xero-invoice-to-job match, and an unmatched
                // Xero row carries no job id, so neither column is unique on
                // its own; the pair is what identifies a row.
                key={`${row.job_id ?? 'unmatched'}-${row.invoice_numbers ?? row.date ?? ''}`}
                className="border-b border-gray-100 hover:bg-gray-50"
              >
                <td className="px-3 py-2">
                  {row.job_start_date === null ? (
                    <span className="text-gray-400">—</span>
                  ) : (
                    formatDate(row.job_start_date)
                  )}
                </td>
                <td className="px-3 py-2">
                  {row.date === null ? (
                    <span className="text-gray-400">—</span>
                  ) : (
                    formatDate(row.date)
                  )}
                </td>
                <td className="px-3 py-2">{row.company_name}</td>
                <td className="px-3 py-2">
                  <OptionalCell value={row.invoice_numbers} />
                </td>
                <td className="px-3 py-2">
                  {row.job_id === null ? (
                    <span className="text-gray-400">—</span>
                  ) : (
                    <Link
                      to="/jobs/$jobId"
                      params={{ jobId: row.job_id }}
                      className="text-blue-600 hover:underline"
                    >
                      {row.job_number} - {row.job_name}
                    </Link>
                  )}
                </td>
                <td className="px-3 py-2 text-gray-500">
                  <OptionalCell value={row.note} />
                </td>
                <td className="px-3 py-2 text-right">
                  <MoneyCell value={row.total_invoiced} />
                </td>
                <td className="px-3 py-2 text-right">
                  <MoneyCell value={row.job_revenue} />
                </td>
                <td
                  className={`px-3 py-2 text-right font-medium ${varianceToneClass(row.variance)}`}
                >
                  {formatCurrency(row.variance)}
                </td>
                <td className="px-3 py-2 text-right font-medium">
                  {row.variance_all_time === null ? (
                    <span className="text-gray-400">—</span>
                  ) : (
                    <span className={varianceToneClass(row.variance_all_time)}>
                      {formatCurrency(row.variance_all_time)}
                    </span>
                  )}
                </td>
              </tr>
            )}
          />
        </>
      )}
    </div>
  )
}
