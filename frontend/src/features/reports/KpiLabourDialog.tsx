import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation('reports')
  return (
    <KpiDialog
      open={open}
      onClose={onClose}
      automationId="KpiLabourDialog"
      title={t('labourDialog.title', { month: formatMonth(month) })}
      description={t('labourDialog.description')}
    >
      <Section title={t('labourDialog.hours')}>
        <Stats>
          <Stat
            label={t('labourDialog.totalHours')}
            title={t('labourDialog.titles.totalHours')}
            value={formatHoursDisplay(totals.total_hours)}
            note={t('labourDialog.totalHoursNote')}
          />
          <Stat
            label={t('labourDialog.billableHours')}
            title={t('labourDialog.titles.billableHours')}
            value={formatHoursDisplay(totals.billable_hours)}
            note={t('labourDialog.billableHoursNote')}
          />
          <Stat
            label={t('labourDialog.shopHours')}
            title={t('labourDialog.titles.shopHours')}
            value={formatHoursDisplay(totals.shop_hours)}
            note={t('labourDialog.shopHoursNote')}
          />
          <Stat
            label={t('labourDialog.billedPerActiveDay')}
            value={hoursText(totals.avg_active_day_billable_hours)}
            note={t('labourDialog.billedPerActiveDayNote')}
          />
        </Stats>
      </Section>
      <Section title={t('labourDialog.money')}>
        <div className="space-y-1">
          <Row
            label={t('labourDialog.labourRevenue')}
            value={money(totals.time_revenue)}
            title={t('labourDialog.titles.labourRevenue')}
          />
          <Row
            label={t('labourDialog.labourCost')}
            value={money(totals.staff_cost)}
            title={t('labourDialog.titles.labourCost')}
          />
          <Row
            label={t('labourDialog.labourProfit')}
            title={t('labourDialog.titles.labourProfit')}
            value={money(totals.labour_profit)}
            strong
            automationId="KpiLabourDialog-labour-profit"
          />
          <Row
            label={t('labourDialog.averageRate')}
            title={t('labourDialog.titles.averageRate')}
            value={moneyText(totals.avg_labour_rate, money)}
            automationId="KpiLabourDialog-avg-rate"
          />
        </div>
      </Section>
      <Section title={t('labourDialog.efficiency')}>
        <Stats>
          <Stat
            label={t('labourDialog.utilisation')}
            title={t('labourDialog.titles.utilisation')}
            value={ratioText(totals.billable_percentage)}
            note={t('labourDialog.utilisationNote')}
          />
          <Stat
            label={t('labourDialog.shopShare')}
            value={ratioText(totals.shop_percentage)}
            note={t('labourDialog.shopShareNote')}
          />
          <Stat
            label={t('labourDialog.labourMargin')}
            title={t('labourDialog.titles.labourMargin')}
            value={ratioText(totals.labour_margin)}
            note={t('labourDialog.labourMarginNote')}
            automationId="KpiLabourDialog-labour-margin"
          />
        </Stats>
      </Section>
      <Section title={t('labourDialog.byDay')}>
        <DailyTable
          automationId="KpiLabourDialog-daily"
          days={days}
          columns={[
            {
              header: t('labourDialog.totalHours'),
              cell: (day) => formatHoursDisplay(day.total_hours),
              total: formatHoursDisplay(totals.total_hours),
            },
            {
              header: t('labourDialog.billableHours'),
              cell: (day) => formatHoursDisplay(day.billable_hours),
              total: formatHoursDisplay(totals.billable_hours),
            },
            {
              header: t('labourDialog.shopHours'),
              cell: (day) => formatHoursDisplay(day.shop_hours),
              total: formatHoursDisplay(totals.shop_hours),
            },
            {
              header: t('labourDialog.labourCost'),
              cell: (day) => money(day.details.staff_cost),
              total: money(totals.staff_cost),
            },
            {
              header: t('labourDialog.labourRevenue'),
              cell: (day) => money(day.details.time_revenue),
              total: money(totals.time_revenue),
            },
          ]}
        />
      </Section>
    </KpiDialog>
  )
}
