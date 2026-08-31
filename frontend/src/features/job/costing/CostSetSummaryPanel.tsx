import type { CostSetOut } from '@/api'
import { formatCurrency, formatPercentage } from '@/lib/format'

const HOURS = new Intl.NumberFormat('en-NZ', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
})

interface CostSetSummaryPanelProps {
  title: string
  automationId: string
  summary: CostSetOut['summary'] | undefined
  /** The cost-set query errored (with no data to show). */
  isError: boolean
}

/**
 * The one cost-set summary panel: Revenue, Cost, Hours, Profit margin,
 * rendered verbatim from the server-owned summary (ADR 0046) on the
 * Estimate, Quote and Actual tabs alike. v1 gave each tab its own summary
 * card; one implementation serves all three here (ADR 0039).
 */
export function CostSetSummaryPanel({
  title,
  automationId,
  summary,
  isError,
}: CostSetSummaryPanelProps) {
  return (
    <section
      data-automation-id={automationId}
      className="rounded-xl border border-slate-200 bg-white p-4"
    >
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {summary ? (
        <dl className="mt-3 space-y-1.5 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-600">Revenue</dt>
            <dd className="font-semibold tabular-nums">{formatCurrency(summary.rev)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-600">Cost</dt>
            <dd className="font-medium tabular-nums">{formatCurrency(summary.cost)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-600">Hours</dt>
            <dd className="font-medium tabular-nums">{HOURS.format(summary.hours)}</dd>
          </div>
          <div className="flex justify-between border-t border-slate-200 pt-1.5">
            <dt className="text-slate-600">Profit margin</dt>
            <dd className="font-medium tabular-nums">
              {/* null margin means undefined (zero revenue), not 0.0% */}
              {summary.profitMargin === null ? '—' : formatPercentage(summary.profitMargin)}
            </dd>
          </div>
        </dl>
      ) : isError ? (
        // No fabricated zeros: a failed load must not read as a $0 cost set.
        // Data wins over a failed refetch — the last good summary beats an
        // error banner mid-edit.
        <p className="mt-2 text-sm font-medium text-red-700">
          Could not load the {title.toLowerCase()}. Reload the page.
        </p>
      ) : (
        <p className="mt-2 text-sm text-slate-500">Loading…</p>
      )}
    </section>
  )
}
