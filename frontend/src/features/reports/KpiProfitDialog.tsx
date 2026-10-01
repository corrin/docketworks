import type { KpiMonthlyTotalsOut, KpiThresholdsOut } from '@/api'
import { formatMonth } from '@/lib/format'

import { KpiDialog, Row, Section, Stat, Stats } from './kpiDialogParts'
import { ratioText, signClass, type MoneyFormatter } from './kpiDisplay'

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
  return (
    <KpiDialog
      open={open}
      onClose={onClose}
      automationId="KpiProfitDialog"
      title={`Profit — ${formatMonth(month)}`}
      description="Revenue less cost is gross profit; less overhead to date is net profit"
    >
      <Section title="Profit flow">
        <div className="space-y-1">
          <Row label="Total revenue" value={money(totals.total_revenue)} />
          <Row label="less total cost" value={money(totals.total_cost)} indent />
          <Row
            label="Gross profit"
            value={money(totals.gross_profit)}
            strong
            automationId="KpiProfitDialog-gross-profit"
          />
          <Row label="less overhead to date" value={money(totals.elapsed_target)} indent />
          <Row
            label="Net profit"
            value={money(totals.net_profit)}
            strong
            className={signClass(totals.net_profit)}
            automationId="KpiProfitDialog-net-profit"
          />
        </div>
      </Section>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Section title="Revenue">
          <div className="space-y-1">
            <Row label="Labour" value={money(totals.time_revenue)} />
            <Row label="Materials" value={money(totals.material_revenue)} />
            <Row label="Adjustments" value={money(totals.adjustment_revenue)} />
          </div>
        </Section>
        <Section title="Cost">
          <div className="space-y-1">
            <Row label="Labour" value={money(totals.staff_cost)} />
            <Row label="Materials" value={money(totals.material_cost)} />
            <Row label="Adjustments" value={money(totals.adjustment_cost)} />
          </div>
        </Section>
      </div>
      <Section title="Margins">
        <Stats>
          <Stat
            label="Gross margin"
            value={ratioText(totals.gross_margin)}
            note="Gross profit of revenue"
          />
          <Stat
            label="Net margin"
            value={ratioText(totals.net_margin)}
            note="Net profit of revenue"
            automationId="KpiProfitDialog-net-margin"
          />
          <Stat
            label="Labour share"
            value={ratioText(totals.labour_revenue_share)}
            note="Labour of total revenue"
          />
          <Stat
            label="Average gross profit"
            value={money(totals.avg_weekday_gp)}
            note="Per weekday"
          />
        </Stats>
      </Section>
      <Section title="Overhead target">
        <div className="space-y-1">
          <Row
            label="Daily target (overhead per weekday)"
            value={money(thresholds.kpi_daily_gp_target)}
          />
          <Row label="Weekdays in the month" value={String(totals.weekdays)} />
          <Row label="Weekdays elapsed" value={String(totals.elapsed_weekdays)} />
          <Row label="Overhead to date" value={money(totals.elapsed_target)} />
          <Row
            label="Month target"
            value={money(totals.month_target)}
            automationId="KpiProfitDialog-month-target"
          />
          <Row
            label="Gross profit against month target"
            value={ratioText(totals.month_target_achievement)}
            strong
            automationId="KpiProfitDialog-achievement"
          />
        </div>
      </Section>
    </KpiDialog>
  )
}
