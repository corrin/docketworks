import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation('reports')
  if (day === null) return null
  const { details } = day
  const profit = details.profit_breakdown
  return (
    <KpiDialog
      open
      onClose={onClose}
      automationId="KpiDayDetailsDialog"
      title={
        day.holiday
          ? t('dayDialog.titleHoliday', { date: formatDateLong(day.date) })
          : formatDateLong(day.date)
      }
      description={t('dayDialog.description')}
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Section title={t('dayDialog.revenue')}>
          <div className="space-y-1">
            <Row label={t('dayDialog.labour')} value={money(details.time_revenue)} />
            <Row label={t('dayDialog.materials')} value={money(details.material_revenue)} />
            <Row label={t('dayDialog.adjustments')} value={money(details.adjustment_revenue)} />
            <Row label={t('dayDialog.totalRevenue')} value={money(details.total_revenue)} strong />
          </div>
        </Section>
        <Section title={t('dayDialog.cost')}>
          <div className="space-y-1">
            <Row label={t('dayDialog.labour')} value={money(details.staff_cost)} />
            <Row label={t('dayDialog.materials')} value={money(details.material_cost)} />
            <Row label={t('dayDialog.adjustments')} value={money(details.adjustment_cost)} />
            <Row label={t('dayDialog.totalCost')} value={money(details.total_cost)} strong />
          </div>
        </Section>
      </div>
      <Section title={t('dayDialog.grossProfit')}>
        <Stats>
          <Stat label={t('dayDialog.labour')} value={money(profit.labour_profit)} />
          <Stat label={t('dayDialog.materials')} value={money(profit.material_profit)} />
          <Stat label={t('dayDialog.adjustments')} value={money(profit.adjustment_profit)} />
          <Stat
            label={t('dayDialog.grossProfit')}
            value={money(day.gross_profit)}
            automationId="KpiDayDetailsDialog-gross-profit"
          />
        </Stats>
      </Section>
      <Section title={t('dayDialog.profitByJob')}>
        {details.job_breakdown.length === 0 ? (
          <p className="text-sm text-gray-500">{t('dayDialog.noJobs')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-automation-id="KpiDayDetailsDialog-jobs">
              <thead>
                <tr className="border-b border-gray-300 text-xs text-gray-600">
                  <th className="px-3 py-2 text-left font-semibold">
                    {t('dayDialog.columns.job')}
                  </th>
                  <th className="px-3 py-2 text-right font-semibold">{t('dayDialog.labour')}</th>
                  <th className="px-3 py-2 text-right font-semibold">{t('dayDialog.materials')}</th>
                  <th className="px-3 py-2 text-right font-semibold">
                    {t('dayDialog.adjustments')}
                  </th>
                  <th className="px-3 py-2 text-right font-semibold">
                    {t('dayDialog.columns.total')}
                  </th>
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
