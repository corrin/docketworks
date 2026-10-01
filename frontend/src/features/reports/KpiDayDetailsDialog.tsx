import { Link } from '@tanstack/react-router'

import type { KpiDayDataOut } from '@/api'
import { formatDateLong } from '@/lib/format'

import { KpiDialog, Row, Section, Stat, Stats } from './kpiDialogParts'
import type { MoneyFormatter } from './kpiDisplay'

interface KpiDayDetailsDialogProps {
  day: KpiDayDataOut | null
  money: MoneyFormatter
  onClose: () => void
}

/**
 * One day: revenue, cost and profit by stream, then profit by job. Every
 * figure is a field of the day's `details`; the three profits are its
 * `profit_breakdown`, the same numbers the calendar cell shows. Job numbers
 * link to the job — the one navigation out of the report.
 */
export function KpiDayDetailsDialog({ day, money, onClose }: KpiDayDetailsDialogProps) {
  if (day === null) return null
  const { details } = day
  const profit = details.profit_breakdown
  return (
    <KpiDialog
      open
      onClose={onClose}
      automationId="KpiDayDetailsDialog"
      title={`${formatDateLong(day.date)}${day.holiday ? ' (Holiday)' : ''}`}
      description="Revenue, cost and profit for the day, and the jobs that made it"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Section title="Revenue">
          <div className="space-y-1">
            <Row label="Labour" value={money(details.time_revenue)} />
            <Row label="Materials" value={money(details.material_revenue)} />
            <Row label="Adjustments" value={money(details.adjustment_revenue)} />
            <Row label="Total revenue" value={money(details.total_revenue)} strong />
          </div>
        </Section>
        <Section title="Cost">
          <div className="space-y-1">
            <Row label="Labour" value={money(details.staff_cost)} />
            <Row label="Materials" value={money(details.material_cost)} />
            <Row label="Adjustments" value={money(details.adjustment_cost)} />
            <Row label="Total cost" value={money(details.total_cost)} strong />
          </div>
        </Section>
      </div>
      <Section title="Gross profit">
        <Stats>
          <Stat label="Labour" value={money(profit.labour_profit)} />
          <Stat label="Materials" value={money(profit.material_profit)} />
          <Stat label="Adjustments" value={money(profit.adjustment_profit)} />
          <Stat
            label="Gross profit"
            value={money(day.gross_profit)}
            automationId="KpiDayDetailsDialog-gross-profit"
          />
        </Stats>
      </Section>
      <Section title="Profit by job">
        {details.job_breakdown.length === 0 ? (
          <p className="text-sm text-gray-500">No job data available for this day</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-automation-id="KpiDayDetailsDialog-jobs">
              <thead>
                <tr className="border-b border-gray-300 text-xs text-gray-600">
                  <th className="px-3 py-2 text-left font-semibold">Job</th>
                  <th className="px-3 py-2 text-right font-semibold">Labour</th>
                  <th className="px-3 py-2 text-right font-semibold">Materials</th>
                  <th className="px-3 py-2 text-right font-semibold">Adjustments</th>
                  <th className="px-3 py-2 text-right font-semibold">Total</th>
                </tr>
              </thead>
              <tbody>
                {/* Server order: most profitable first. */}
                {details.job_breakdown.map((job) => (
                  <tr key={job.job_id} className="border-b border-gray-200 hover:bg-gray-100">
                    <td className="px-3 py-1.5">
                      <Link
                        to="/jobs/$jobId"
                        params={{ jobId: job.job_id }}
                        title={`${job.job_name} — ${job.company_name}`}
                        className="text-blue-600 hover:underline"
                        data-automation-id={`KpiDayDetailsDialog-job-${job.job_id}`}
                      >
                        {job.job_number}
                      </Link>
                    </td>
                    <td className="px-3 py-1.5 text-right">{money(job.labour_profit)}</td>
                    <td className="px-3 py-1.5 text-right">{money(job.material_profit)}</td>
                    <td className="px-3 py-1.5 text-right">{money(job.adjustment_profit)}</td>
                    <td className="px-3 py-1.5 text-right font-medium">{money(job.profit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </KpiDialog>
  )
}
