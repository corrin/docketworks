import type { KpiDayDataOut, KpiMonthlyTotalsOut } from '@/api'
import { formatHoursDisplay, formatMonth } from '@/lib/format'

import { DailyTable, KpiDialog, Row, Section, Stat, Stats } from './kpiDialogParts'
import { hoursText, moneyText, ratioText, type MoneyFormatter } from './kpiDisplay'

interface KpiLabourDialogProps {
  open: boolean
  month: string
  totals: KpiMonthlyTotalsOut
  days: readonly KpiDayDataOut[]
  money: MoneyFormatter
  onClose: () => void
}

/**
 * The month's labour: hours, money, efficiency, and a day-by-day table.
 * v1 summed the days for shop hours, labour cost and labour revenue while
 * reading the hours totals from the server, and estimated a "shop labour
 * cost" pro rata by hours; every figure here is a served total and the
 * estimate is gone (docs/accepted-api-differences.yml).
 */
export function KpiLabourDialog({
  open,
  month,
  totals,
  days,
  money,
  onClose,
}: KpiLabourDialogProps) {
  return (
    <KpiDialog
      open={open}
      onClose={onClose}
      automationId="KpiLabourDialog"
      title={`Labour — ${formatMonth(month)}`}
      description="Hours, cost and revenue from time entries"
    >
      <Section title="Hours">
        <Stats>
          <Stat
            label="Total hours"
            value={formatHoursDisplay(totals.total_hours)}
            note="All recorded time"
          />
          <Stat
            label="Billable hours"
            value={formatHoursDisplay(totals.billable_hours)}
            note="Chargeable to a customer"
          />
          <Stat
            label="Shop hours"
            value={formatHoursDisplay(totals.shop_hours)}
            note="Workshop and production"
          />
          <Stat
            label="Billed per active day"
            value={hoursText(totals.avg_active_day_billable_hours)}
            note="Days with any hours"
          />
        </Stats>
      </Section>
      <Section title="Money">
        <div className="space-y-1">
          <Row label="Labour revenue" value={money(totals.time_revenue)} />
          <Row label="Labour cost" value={money(totals.staff_cost)} />
          <Row
            label="Labour profit"
            value={money(totals.labour_profit)}
            strong
            automationId="KpiLabourDialog-labour-profit"
          />
          <Row
            label="Average rate per billable hour"
            value={moneyText(totals.avg_labour_rate, money)}
            automationId="KpiLabourDialog-avg-rate"
          />
        </div>
      </Section>
      <Section title="Efficiency">
        <Stats>
          <Stat
            label="Utilisation"
            value={ratioText(totals.billable_percentage)}
            note="Billable of total hours"
          />
          <Stat
            label="Shop share"
            value={ratioText(totals.shop_percentage)}
            note="Shop of total hours"
          />
          <Stat
            label="Labour margin"
            value={ratioText(totals.labour_margin)}
            note="Profit of labour revenue"
            automationId="KpiLabourDialog-labour-margin"
          />
        </Stats>
      </Section>
      <Section title="By day">
        <DailyTable
          automationId="KpiLabourDialog-daily"
          days={days}
          columns={[
            {
              header: 'Total hours',
              cell: (day) => formatHoursDisplay(day.total_hours),
              total: formatHoursDisplay(totals.total_hours),
            },
            {
              header: 'Billable hours',
              cell: (day) => formatHoursDisplay(day.billable_hours),
              total: formatHoursDisplay(totals.billable_hours),
            },
            {
              header: 'Shop hours',
              cell: (day) => formatHoursDisplay(day.shop_hours),
              total: formatHoursDisplay(totals.shop_hours),
            },
            {
              header: 'Labour cost',
              cell: (day) => money(day.details.staff_cost),
              total: money(totals.staff_cost),
            },
            {
              header: 'Labour revenue',
              cell: (day) => money(day.details.time_revenue),
              total: money(totals.time_revenue),
            },
          ]}
        />
      </Section>
    </KpiDialog>
  )
}
