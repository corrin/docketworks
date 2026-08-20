import type { ReactNode } from 'react'

import type { ForecastMonthOut } from '@/api'
import { ListTable } from '@/features/shared/ListTable'
import { formatCurrency, formatPercentage } from '@/lib/format'

import { varianceBadgeClass, varianceToneClass } from './variance'

interface SalesForecastMonthTableProps {
  months: readonly ForecastMonthOut[] | undefined
  isPending: boolean
  isError: boolean
  onRetry: () => void
  onSelect: (month: string) => void
  /** Opus: rendered above the rows once the query resolves — the summary
      cards, which must not appear beside a loading or errored table. */
  children: ReactNode
}

/** The month comparison: one row per month, newest first, each a way in to
    the invoices and jobs behind it. */
export function SalesForecastMonthTable({
  months,
  isPending,
  isError,
  onRetry,
  onSelect,
  children,
}: SalesForecastMonthTableProps) {
  return (
    <ListTable
      isPending={isPending}
      isError={isError}
      onRetry={onRetry}
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
      renderRow={(month: ForecastMonthOut) => (
        <tr
          key={month.month}
          data-automation-id={`SalesForecastReport-month-${month.month}`}
          className="cursor-pointer border-b border-gray-100 hover:bg-blue-50"
          onClick={() => onSelect(month.month)}
        >
          <td className="px-3 py-2 font-medium text-gray-900">{month.month_label}</td>
          <td className="px-3 py-2 text-right">{formatCurrency(month.xero_sales)}</td>
          <td className="px-3 py-2 text-right">{formatCurrency(month.jm_sales)}</td>
          <td className={`px-3 py-2 text-right font-medium ${varianceToneClass(month.variance)}`}>
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
      {children}
    </ListTable>
  )
}
