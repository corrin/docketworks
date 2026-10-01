import type { KpiMonthlyTotalsOut } from '@/api'
import { Button } from '@/components/ui/button'
import { SummaryCard } from '@/features/shared/SummaryCard'
import { formatHoursDisplay } from '@/lib/format'

import {
  GRADE_WORDING,
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
  return (
    <Button
      variant="ghost"
      size="sm"
      data-automation-id={`KpiCalendarReport-card-${dialog}-breakdown`}
      onClick={() => onOpen(dialog)}
    >
      Breakdown
    </Button>
  )
}

function SubLine({ children }: { children: string }) {
  return <div className="text-sm font-normal text-gray-500">{children}</div>
}

/**
 * Labour, Materials, Adjustments and Profit for the month. Every figure is a
 * field of `monthly_totals`: v1 summed the day cells for some of these and
 * read the totals for others, and the two disagreed whenever a weekend
 * carried money.
 */
export function KpiSummaryCards({ totals, target, money, onOpen }: KpiSummaryCardsProps) {
  const grade = monthColor(totals, target)
  return (
    <div
      data-automation-id="KpiCalendarReport-summary-cards"
      className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <SummaryCard
        label="Labour"
        valueAutomationId="KpiCalendarReport-card-labour-value"
        action={<BreakdownButton dialog="labour" onOpen={onOpen} />}
      >
        {formatHoursDisplay(totals.billable_hours)} billed
        <SubLine>{`${formatHoursDisplay(totals.total_hours)} total`}</SubLine>
        <SubLine>{`${formatHoursDisplay(totals.avg_active_day_billable_hours)} billed per active day`}</SubLine>
        <div
          className={`text-sm font-medium ${kpiInkClass(grade)}`}
          data-automation-id="KpiCalendarReport-card-labour-grade"
        >
          {GRADE_WORDING[grade]}
        </div>
      </SummaryCard>
      <SummaryCard
        label="Materials"
        valueAutomationId="KpiCalendarReport-card-material-value"
        action={<BreakdownButton dialog="material" onOpen={onOpen} />}
      >
        {money(totals.material_profit)}
        <SubLine>{`${money(totals.material_revenue)} revenue`}</SubLine>
        <SubLine>{`${money(totals.material_cost)} cost`}</SubLine>
        <SubLine>{`${ratioText(totals.material_margin)} margin`}</SubLine>
      </SummaryCard>
      <SummaryCard
        label="Adjustments"
        valueAutomationId="KpiCalendarReport-card-adjustment-value"
        action={<BreakdownButton dialog="adjustment" onOpen={onOpen} />}
      >
        {money(totals.adjustment_profit)}
        <SubLine>{`${money(totals.adjustment_revenue)} revenue`}</SubLine>
        <SubLine>{`${money(totals.adjustment_cost)} cost`}</SubLine>
        <SubLine>{`${ratioText(totals.adjustment_margin)} margin`}</SubLine>
      </SummaryCard>
      <SummaryCard
        label="Net profit"
        valueAutomationId="KpiCalendarReport-card-profit-value"
        action={<BreakdownButton dialog="profit" onOpen={onOpen} />}
      >
        <span className={signClass(totals.net_profit)}>{money(totals.net_profit)}</span>
        <SubLine>{`${money(totals.total_revenue)} revenue`}</SubLine>
        <SubLine>{`${money(totals.gross_profit)} gross profit`}</SubLine>
        <SubLine>{`${ratioText(totals.net_margin)} net margin`}</SubLine>
      </SummaryCard>
    </div>
  )
}
