import type { KpiDayDataOut, KpiMonthlyTotalsOut } from '@/api'
import { formatMonth } from '@/lib/format'

import { DailyTable, KpiDialog, Section, Stat, Stats } from './kpiDialogParts'
import { ratioText, type MoneyFormatter } from './kpiDisplay'

/** The two non-labour streams a cost line can be. */
export type KpiStream = 'material' | 'adjustment'

const STREAM_TITLE: Record<KpiStream, string> = {
  material: 'Materials',
  adjustment: 'Adjustments',
}

const STREAM_DESCRIPTION: Record<KpiStream, string> = {
  material: 'Stock and purchases charged to jobs',
  adjustment: 'Price adjustments on jobs',
}

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
      title={`${STREAM_TITLE[stream]} — ${formatMonth(month)}`}
      description={STREAM_DESCRIPTION[stream]}
    >
      <Section title="Month">
        <Stats>
          <Stat label="Revenue" value={money(revenue)} />
          <Stat label="Cost" value={money(cost)} />
          <Stat
            label="Profit"
            value={money(profit)}
            note="Revenue less cost"
            automationId={`KpiStreamDialog-${stream}-profit`}
          />
          <Stat label="Margin" value={ratioText(margin)} note="Profit of revenue" />
        </Stats>
      </Section>
      <Section title="Materials and adjustments together">
        {/* The sums this report does in the browser: two displayed server
            figures added, no denominator (owner, 2026-10-01). The share is
            the complement of a served ratio. */}
        <Stats>
          <Stat
            label="Non-labour revenue"
            value={money(totals.material_revenue + totals.adjustment_revenue)}
          />
          <Stat
            label="Non-labour cost"
            value={money(totals.material_cost + totals.adjustment_cost)}
          />
          <Stat
            label="Non-labour profit"
            value={money(totals.material_profit + totals.adjustment_profit)}
          />
          <Stat
            label="Non-labour share"
            value={ratioText(
              totals.labour_revenue_share === null ? null : 100 - totals.labour_revenue_share,
            )}
            note="Of total revenue"
          />
        </Stats>
      </Section>
      <Section title="By day">
        <DailyTable
          automationId={`KpiStreamDialog-${stream}-daily`}
          days={days}
          columns={[
            {
              header: 'Revenue',
              cell: (day) => money(day.details[`${stream}_revenue`]),
              total: money(revenue),
            },
            {
              header: 'Cost',
              cell: (day) => money(day.details[`${stream}_cost`]),
              total: money(cost),
            },
            {
              header: 'Profit',
              cell: (day) => money(day.details.profit_breakdown[`${stream}_profit`]),
              total: money(profit),
            },
          ]}
        />
      </Section>
    </KpiDialog>
  )
}
