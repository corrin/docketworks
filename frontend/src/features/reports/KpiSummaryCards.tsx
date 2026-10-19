import { useTranslation } from 'react-i18next'

import type { KpiMonthlyTotalsOut } from '@/api'
import { Button } from '@/components/ui/button'
import { SummaryCard } from '@/features/shared/SummaryCard'
import { formatHoursDisplay } from '@/lib/format'

import {
  gradeWording,
  hoursText,
  kpiInkClass,
  monthColor,
  ratioText,
  signClass,
  type KpiTarget,
  type MoneyFormatter,
} from './kpiDisplay'

/** The four card breakdowns. Materials and Adjustments are the same dialog
    over a different stream — see KpiStreamDialog. */
export type KpiCardDialog = 'labour' | 'material' | 'adjustment' | 'profit'

interface KpiSummaryCardsProps {
  totals: KpiMonthlyTotalsOut
  target: KpiTarget
  money: MoneyFormatter
  onOpen: (dialog: KpiCardDialog) => void
}

function BreakdownButton({
  dialog,
  onOpen,
}: {
  dialog: KpiCardDialog
  onOpen: (d: KpiCardDialog) => void
}) {
  const { t } = useTranslation('reports')
  return (
    <Button
      variant="ghost"
      size="sm"
      data-automation-id={`KpiCalendarReport-card-${dialog}-breakdown`}
      onClick={() => onOpen(dialog)}
    >
      {t('summaryCards.breakdown')}
    </Button>
  )
}

function SubLine({ children, title }: { children: string; title?: string }) {
  return (
    <div className="text-sm font-normal text-gray-500" title={title}>
      {children}
    </div>
  )
}

/**
 * Labour, Materials, Adjustments and Profit for the month. Every figure is a
 * field of `monthly_totals`: v1 summed the day cells for some of these and
 * read the totals for others, and the two disagreed whenever a weekend
 * carried money.
 */
export function KpiSummaryCards({ totals, target, money, onOpen }: KpiSummaryCardsProps) {
  const { t } = useTranslation('reports')
  const grade = monthColor(totals, target)
  return (
    <div
      data-automation-id="KpiCalendarReport-summary-cards"
      className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <SummaryCard
        label={t('summaryCards.labour')}
        valueAutomationId="KpiCalendarReport-card-labour-value"
        action={<BreakdownButton dialog="labour" onOpen={onOpen} />}
      >
        {t('summaryCards.billed', { hours: formatHoursDisplay(totals.billable_hours) })}
        <SubLine>
          {t('summaryCards.totalHours', { hours: formatHoursDisplay(totals.total_hours) })}
        </SubLine>
        <SubLine title={t('summaryCards.titles.billedPerActiveDay')}>
          {t('summaryCards.billedPerActiveDay', {
            hours: hoursText(totals.avg_active_day_billable_hours),
          })}
        </SubLine>
        <div
          className={`text-sm font-medium ${kpiInkClass(grade)}`}
          data-automation-id="KpiCalendarReport-card-labour-grade"
        >
          {gradeWording(grade)}
        </div>
      </SummaryCard>
      <SummaryCard
        label={t('summaryCards.materials')}
        title={t('summaryCards.titles.materials')}
        valueAutomationId="KpiCalendarReport-card-material-value"
        action={<BreakdownButton dialog="material" onOpen={onOpen} />}
      >
        {money(totals.material_profit)}
        <SubLine>{t('summaryCards.revenue', { amount: money(totals.material_revenue) })}</SubLine>
        <SubLine>{t('summaryCards.cost', { amount: money(totals.material_cost) })}</SubLine>
        <SubLine title={t('summaryCards.titles.margin')}>
          {t('summaryCards.margin', { ratio: ratioText(totals.material_margin) })}
        </SubLine>
      </SummaryCard>
      <SummaryCard
        label={t('summaryCards.adjustments')}
        title={t('summaryCards.titles.adjustments')}
        valueAutomationId="KpiCalendarReport-card-adjustment-value"
        action={<BreakdownButton dialog="adjustment" onOpen={onOpen} />}
      >
        {money(totals.adjustment_profit)}
        <SubLine>{t('summaryCards.revenue', { amount: money(totals.adjustment_revenue) })}</SubLine>
        <SubLine>{t('summaryCards.cost', { amount: money(totals.adjustment_cost) })}</SubLine>
        <SubLine title={t('summaryCards.titles.margin')}>
          {t('summaryCards.margin', { ratio: ratioText(totals.adjustment_margin) })}
        </SubLine>
      </SummaryCard>
      <SummaryCard
        label={t('summaryCards.netProfit')}
        title={t('summaryCards.titles.netProfit')}
        valueAutomationId="KpiCalendarReport-card-profit-value"
        action={<BreakdownButton dialog="profit" onOpen={onOpen} />}
      >
        <span className={signClass(totals.net_profit)}>{money(totals.net_profit)}</span>
        <SubLine>{t('summaryCards.revenue', { amount: money(totals.total_revenue) })}</SubLine>
        <SubLine>{t('summaryCards.grossProfit', { amount: money(totals.gross_profit) })}</SubLine>
        <SubLine title={t('summaryCards.titles.netMargin')}>
          {t('summaryCards.netMargin', { ratio: ratioText(totals.net_margin) })}
        </SubLine>
      </SummaryCard>
    </div>
  )
}
