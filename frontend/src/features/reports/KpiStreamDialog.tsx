import { useTranslation } from 'react-i18next'

import type { KpiDayDataOut, KpiMonthlyTotalsOut } from '@/api'
import { formatMonth } from '@/lib/format'

import { DailyTable, KpiDialog, Section, Stat, Stats } from './kpiDialogParts'
import { ratioText, type MoneyFormatter } from './kpiDisplay'

/** The two non-labour streams a cost line can be. */
export type KpiStream = 'material' | 'adjustment'

interface KpiStreamDialogProps {
  stream: KpiStream | null
  month: string
  totals: KpiMonthlyTotalsOut
  days: readonly KpiDayDataOut[]
  money: MoneyFormatter
  onClose: () => void
}

/**
 * The month's materials OR adjustments: one component over a stream
 * discriminant rather than two mirrored files. v1 had one Materials modal
 * and wired the Adjustments card to it, so adjustments never had a
 * breakdown of their own (ADR 0039: two near-identical files is how that
 * kind of miswiring survives review).
 *
 * The field names are built from the stream, which the wire types check:
 * `material_revenue` and `adjustment_revenue` are both keys of
 * `monthly_totals`, and a stream the server did not name is a type error.
 */
export function KpiStreamDialog({
  stream,
  month,
  totals,
  days,
  money,
  onClose,
}: KpiStreamDialogProps) {
  const { t } = useTranslation('reports')
  if (stream === null) return null
  const revenue = totals[`${stream}_revenue`]
  const cost = totals[`${stream}_cost`]
  const profit = totals[`${stream}_profit`]
  const margin = totals[`${stream}_margin`]
  return (
    <KpiDialog
      open
      onClose={onClose}
      automationId={`KpiStreamDialog-${stream}`}
      title={t(`streamDialog.${stream}.title`, { month: formatMonth(month) })}
      description={t(`streamDialog.${stream}.description`)}
    >
      <Section title={t('streamDialog.month')}>
        <Stats>
          <Stat label={t('streamDialog.revenue')} value={money(revenue)} />
          <Stat label={t('streamDialog.cost')} value={money(cost)} />
          <Stat
            label={t('streamDialog.profit')}
            value={money(profit)}
            note={t('streamDialog.profitNote')}
            automationId={`KpiStreamDialog-${stream}-profit`}
          />
          <Stat
            label={t('streamDialog.margin')}
            value={ratioText(margin)}
            note={t('streamDialog.marginNote')}
          />
        </Stats>
      </Section>
      <Section title={t('streamDialog.together')} hint={t('streamDialog.titles.together')}>
        {/* The sums this report does in the browser: two displayed server
            figures added, no denominator (owner, 2026-10-01). The share is
            the complement of a served ratio. */}
        <Stats>
          <Stat
            label={t('streamDialog.nonLabourRevenue')}
            value={money(totals.material_revenue + totals.adjustment_revenue)}
          />
          <Stat
            label={t('streamDialog.nonLabourCost')}
            value={money(totals.material_cost + totals.adjustment_cost)}
          />
          <Stat
            label={t('streamDialog.nonLabourProfit')}
            value={money(totals.material_profit + totals.adjustment_profit)}
          />
          <Stat
            label={t('streamDialog.nonLabourShare')}
            title={t('streamDialog.titles.nonLabourShare')}
            value={ratioText(
              totals.labour_revenue_share === null ? null : 100 - totals.labour_revenue_share,
            )}
            note={t('streamDialog.nonLabourShareNote')}
          />
        </Stats>
      </Section>
      <Section title={t('streamDialog.byDay')}>
        <DailyTable
          automationId={`KpiStreamDialog-${stream}-daily`}
          days={days}
          columns={[
            {
              header: t('streamDialog.revenue'),
              cell: (day) => money(day.details[`${stream}_revenue`]),
              total: money(revenue),
            },
            {
              header: t('streamDialog.cost'),
              cell: (day) => money(day.details[`${stream}_cost`]),
              total: money(cost),
            },
            {
              header: t('streamDialog.profit'),
              cell: (day) => money(day.details.profit_breakdown[`${stream}_profit`]),
              total: money(profit),
            },
          ]}
        />
      </Section>
    </KpiDialog>
  )
}
