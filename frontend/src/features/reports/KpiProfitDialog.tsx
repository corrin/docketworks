import { useTranslation } from 'react-i18next'

import type { KpiMonthlyTotalsOut, KpiThresholdsOut } from '@/api'
import { formatMonth } from '@/lib/format'

import { KpiDialog, Row, Section, Stat, Stats } from './kpiDialogParts'
import { moneyText, ratioText, signClass, type MoneyFormatter } from './kpiDisplay'

interface KpiProfitDialogProps {
  open: boolean
  month: string
  totals: KpiMonthlyTotalsOut
  thresholds: KpiThresholdsOut
  money: MoneyFormatter
  onClose: () => void
}

/**
 * Revenue less cost is gross profit; gross profit less the overhead incurred
 * so far is net profit. All five lines are served, so the flow reconciles by
 * construction. v1 subtracted `kpi_daily_gp_green × working_days` on screen
 * while the server subtracted `kpi_daily_gp_target × elapsed weekdays`, so
 * its "Gross Profit − Projected Expenses" never equalled the Net Profit
 * beneath it.
 *
 * The daily target is overhead (owner ruling 2026-09-01): monthly operating
 * expenses spread across weekdays, so the month's target is the target times
 * its weekdays and a weekend is owed none of it.
 */
export function KpiProfitDialog({
  open,
  month,
  totals,
  thresholds,
  money,
  onClose,
}: KpiProfitDialogProps) {
  const { t } = useTranslation('reports')
  return (
    <KpiDialog
      open={open}
      onClose={onClose}
      automationId="KpiProfitDialog"
      title={t('profitDialog.title', { month: formatMonth(month) })}
      description={t('profitDialog.description')}
    >
      <Section title={t('profitDialog.profitFlow')}>
        <div className="space-y-1">
          <Row label={t('profitDialog.totalRevenue')} value={money(totals.total_revenue)} />
          <Row label={t('profitDialog.lessTotalCost')} value={money(totals.total_cost)} indent />
          <Row
            label={t('profitDialog.grossProfit')}
            value={money(totals.gross_profit)}
            strong
            automationId="KpiProfitDialog-gross-profit"
          />
          <Row label={t('profitDialog.lessOverhead')} value={money(totals.elapsed_target)} indent />
          <Row
            label={t('profitDialog.netProfit')}
            value={money(totals.net_profit)}
            strong
            className={signClass(totals.net_profit)}
            automationId="KpiProfitDialog-net-profit"
          />
        </div>
      </Section>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Section title={t('profitDialog.revenue')}>
          <div className="space-y-1">
            <Row label={t('profitDialog.labour')} value={money(totals.time_revenue)} />
            <Row label={t('profitDialog.materials')} value={money(totals.material_revenue)} />
            <Row label={t('profitDialog.adjustments')} value={money(totals.adjustment_revenue)} />
          </div>
        </Section>
        <Section title={t('profitDialog.cost')}>
          <div className="space-y-1">
            <Row label={t('profitDialog.labour')} value={money(totals.staff_cost)} />
            <Row label={t('profitDialog.materials')} value={money(totals.material_cost)} />
            <Row label={t('profitDialog.adjustments')} value={money(totals.adjustment_cost)} />
          </div>
        </Section>
      </div>
      <Section title={t('profitDialog.margins')}>
        <Stats>
          <Stat
            label={t('profitDialog.grossMargin')}
            value={ratioText(totals.gross_margin)}
            note={t('profitDialog.grossMarginNote')}
          />
          <Stat
            label={t('profitDialog.netMargin')}
            value={ratioText(totals.net_margin)}
            note={t('profitDialog.netMarginNote')}
            automationId="KpiProfitDialog-net-margin"
          />
          <Stat
            label={t('profitDialog.labourShare')}
            value={ratioText(totals.labour_revenue_share)}
            note={t('profitDialog.labourShareNote')}
          />
          <Stat
            label={t('profitDialog.averageGrossProfit')}
            value={moneyText(totals.avg_weekday_gp, money)}
            note={t('profitDialog.perWeekday')}
          />
        </Stats>
      </Section>
      <Section title={t('profitDialog.overheadTarget')}>
        <div className="space-y-1">
          <Row
            label={t('profitDialog.dailyTarget')}
            value={money(thresholds.kpi_daily_gp_target)}
          />
          <Row label={t('profitDialog.weekdaysInMonth')} value={String(totals.weekdays)} />
          <Row label={t('profitDialog.weekdaysElapsed')} value={String(totals.elapsed_weekdays)} />
          <Row label={t('profitDialog.overheadToDate')} value={money(totals.elapsed_target)} />
          <Row
            label={t('profitDialog.monthTarget')}
            value={money(totals.month_target)}
            automationId="KpiProfitDialog-month-target"
          />
          <Row
            label={t('profitDialog.achievement')}
            value={ratioText(totals.month_target_achievement)}
            strong
            automationId="KpiProfitDialog-achievement"
          />
        </div>
      </Section>
    </KpiDialog>
  )
}
