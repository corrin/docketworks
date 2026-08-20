import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { type ForecastComparisonRowOut, salesForecastMonthDetailOptions } from '@/api'
import { ListTable } from '@/features/shared/ListTable'
import { SortHeader } from '@/features/shared/SortHeader'
import { type SortDir, useSortState } from '@/features/shared/useSortState'
import { formatCurrency, formatDate } from '@/lib/format'

import { varianceToneClass } from './variance'

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

const COLUMNS: readonly {
  column: DetailColumn
  label: string
  automationId: string
  align: 'left' | 'right'
}[] = [
  {
    column: 'job_start_date',
    label: 'Job Start',
    automationId: 'SalesForecastReport-header-job-start',
    align: 'left',
  },
  {
    column: 'date',
    label: 'Job Finish',
    automationId: 'SalesForecastReport-header-job-finish',
    align: 'left',
  },
  {
    column: 'company_name',
    label: 'Company',
    automationId: 'SalesForecastReport-header-company',
    align: 'left',
  },
  {
    column: 'invoice_numbers',
    label: 'Invoices',
    automationId: 'SalesForecastReport-header-invoices',
    align: 'left',
  },
  {
    column: 'job_number',
    label: 'Job',
    automationId: 'SalesForecastReport-header-job',
    align: 'left',
  },
  {
    column: 'note',
    label: 'Note',
    automationId: 'SalesForecastReport-header-note',
    align: 'left',
  },
  {
    column: 'total_invoiced',
    label: 'Xero Revenue',
    automationId: 'SalesForecastReport-header-xero-revenue',
    align: 'right',
  },
  {
    column: 'job_revenue',
    label: 'JM Revenue',
    automationId: 'SalesForecastReport-header-jm-revenue',
    align: 'right',
  },
  {
    column: 'variance',
    label: 'Variance',
    automationId: 'SalesForecastReport-header-variance',
    align: 'right',
  },
  {
    column: 'variance_all_time',
    label: 'All-Time Delta',
    automationId: 'SalesForecastReport-header-all-time',
    align: 'right',
  },
]

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
  // One column holds one type across every row, so a mismatch means the wire
  // contract changed under us. Sorting it as equal would hide that behind a
  // table that merely looks unsorted.
  throw new Error(`sales forecast: column ${column} mixes ${typeof a} and ${typeof b}`)
}

/** A blank money cell: a true zero here means "no invoice" and "no revenue",
    which an em dash says and $0.00 does not. */
function MoneyCell({ value }: { value: number }) {
  return value > 0 ? <>{formatCurrency(value)}</> : <Blank />
}

function Blank() {
  return <span className="text-gray-400">—</span>
}

/**
 * The month drill-down. Owns its own query rather than taking rows from the
 * page: the component mounts only once a month is chosen, so `month` is a
 * real value by construction and the query needs neither an `enabled` flag
 * nor a placeholder parameter standing in for "nothing selected yet".
 */
export function SalesForecastDetailTable({ month }: { month: string }) {
  const sort = useSortState<DetailColumn>('date')
  const detail = useQuery(salesForecastMonthDetailOptions({ path: { month } }))

  const rows = detail.data?.rows.toSorted((left, right) =>
    compareRows(left, right, sort.sortBy, sort.sortDir),
  )

  return (
    <ListTable
      isPending={detail.isPending}
      isError={detail.isError}
      onRetry={() => void detail.refetch()}
      loadingLabel="Loading month details..."
      loadingAutomationId="SalesForecastReport-detail-loading"
      errorLabel="Failed to load the month details."
      rows={rows}
      emptyLabel="No invoice or job data for this month"
      automationId="SalesForecastReport-detail-table"
      head={
        <tr className="border-b border-gray-200 text-gray-500">
          {COLUMNS.map((header) => (
            <SortHeader key={header.column} {...header} {...sort} />
          ))}
        </tr>
      }
      renderRow={(row) => (
        <tr
          // Rows are one Xero-invoice-to-job match, and an unmatched Xero row
          // carries no job id, so neither column is unique on its own; the
          // pair is, because a job row always has an id and an unlinked-
          // invoice row always has an invoice number.
          key={`${row.job_id ?? 'unmatched'}-${row.invoice_numbers ?? row.date ?? ''}`}
          className="border-b border-gray-100 hover:bg-gray-50"
        >
          <td className="px-3 py-2">
            {row.job_start_date === null ? <Blank /> : formatDate(row.job_start_date)}
          </td>
          <td className="px-3 py-2">{row.date === null ? <Blank /> : formatDate(row.date)}</td>
          <td className="px-3 py-2">{row.company_name}</td>
          <td className="px-3 py-2">
            {row.invoice_numbers === null ? <Blank /> : row.invoice_numbers}
          </td>
          <td className="px-3 py-2">
            {row.job_id === null ? (
              <Blank />
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
          <td className="px-3 py-2 text-gray-500">{row.note === null ? <Blank /> : row.note}</td>
          <td className="px-3 py-2 text-right">
            <MoneyCell value={row.total_invoiced} />
          </td>
          <td className="px-3 py-2 text-right">
            <MoneyCell value={row.job_revenue} />
          </td>
          <td className={`px-3 py-2 text-right font-medium ${varianceToneClass(row.variance)}`}>
            {formatCurrency(row.variance)}
          </td>
          <td className="px-3 py-2 text-right font-medium">
            {row.variance_all_time === null ? (
              <Blank />
            ) : (
              <span className={varianceToneClass(row.variance_all_time)}>
                {formatCurrency(row.variance_all_time)}
              </span>
            )}
          </td>
        </tr>
      )}
    />
  )
}
