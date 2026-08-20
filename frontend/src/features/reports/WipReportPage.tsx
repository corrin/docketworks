import { useQuery } from '@tanstack/react-query'

import { accountingReportsWipRetrieveOptions } from '@/api'
import { ListTable } from '@/features/shared/ListTable'
import { formatCurrency } from '@/lib/format'
import { SummaryCard } from '@/features/shared/SummaryCard'

/**
 * Work-in-progress report, current date and revenue method only — the date
 * and method controls ship with the slice that asserts on them.
 */
export function WipReportPage() {
  const report = useQuery(accountingReportsWipRetrieveOptions())

  return (
    <div className="min-h-screen p-6">
      <h1 className="text-xl font-bold text-gray-900" data-automation-id="WIPReport-title">
        WIP Report
      </h1>

      <ListTable
        isPending={report.isPending}
        isError={report.isError}
        onRetry={() => void report.refetch()}
        loadingLabel="Loading WIP report..."
        loadingAutomationId="WIPReport-loading"
        errorLabel="Failed to load the WIP report."
        rows={report.data?.jobs}
        emptyLabel="No jobs found"
        automationId="WIPReport-table"
        head={
          <tr className="border-b border-gray-200 text-left text-gray-500">
            <th className="px-3 py-2">Job</th>
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">Company</th>
            <th className="px-3 py-2 text-right">Gross WIP</th>
            <th className="px-3 py-2 text-right">Invoiced</th>
            <th className="px-3 py-2 text-right">Net WIP</th>
          </tr>
        }
        renderRow={(job) => (
          <tr key={job.job_number} className="border-b border-gray-100">
            <td className="px-3 py-2">{job.job_number}</td>
            <td className="px-3 py-2">{job.name}</td>
            <td className="px-3 py-2">{job.company}</td>
            <td className="px-3 py-2 text-right">{formatCurrency(job.gross_wip)}</td>
            <td className="px-3 py-2 text-right">{formatCurrency(job.invoiced)}</td>
            <td className="px-3 py-2 text-right">{formatCurrency(job.net_wip)}</td>
          </tr>
        )}
      >
        {report.data && (
          <div
            data-automation-id="WIPReport-summary-cards"
            className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3"
          >
            <SummaryCard label="Total Gross WIP" valueAutomationId="WIPReport-total-gross-value">
              {formatCurrency(report.data.summary.total_gross)}
            </SummaryCard>
            <SummaryCard label="Total Net WIP" valueAutomationId="WIPReport-total-net-value">
              {formatCurrency(report.data.summary.total_net)}
            </SummaryCard>
            <SummaryCard label="Jobs" valueAutomationId="WIPReport-job-count">
              {report.data.summary.job_count}
            </SummaryCard>
          </div>
        )}
      </ListTable>
    </div>
  )
}
