import { useQuery } from '@tanstack/react-query'

import {
  accountingReportsPayrollWeekReconciliationRetrieveOptions,
  type PayrollStaffWeekRowOut,
} from '@/api'
import { ListTable } from '@/features/shared/ListTable'
import { SegmentedToggle } from '@/features/shared/SegmentedToggle'
import { weeklySearchFromUrl } from '@/features/timesheet'
import { formatCurrency, formatDate } from '@/lib/format'
import { SummaryCard } from '@/features/shared/SummaryCard'

/**
 * What we expect Xero to pay for one week, beside what Xero computed.
 *
 * Read live from the week's pay run rather than the synced pay-slip mirror,
 * which exists only once the run is Posted — by which time a mistake has been
 * paid. This answers in the minutes after posting, while it is still cheap to
 * fix.
 *
 * The rows come from XERO's slips unioned with our time, not from our staff
 * list. That is the whole point: an employee Xero holds on the calendar that
 * we posted nothing for is paid their pay-template hours, typically a full
 * week nobody worked, and iterating the staff DocketWorks knows can never
 * surface them. They appear here as "Not posted".
 */

/** The row's closed status set, straight off the wire contract. */
type RowStatus = PayrollStaffWeekRowOut['status']

// Typed against the generated union rather than Record<string, string>, so a
// status the backend adds is a compile error here instead of a raw code
// rendered to the operator. The taxonomy itself — including which statuses
// count as findings — lives on the server (unposted_count arrives computed).
const STATUS_WORDING: Record<RowStatus, string> = {
  ok: 'Matches',
  mismatch: 'Differs',
  xero_only_departed: 'Left — Xero is still paying them',
  xero_only_unposted: 'Paid, but no hours were posted',
  xero_only_unknown: 'Paid, but DocketWorks has no record',
  xero_only_salaried: 'Salaried — hours are job allocation only',
  jm_only: 'No pay slip',
}

const ROW_TONE: Record<RowStatus, string> = {
  ok: '',
  mismatch: 'text-amber-900',
  xero_only_departed: 'bg-red-50 text-red-900',
  xero_only_unposted: 'bg-red-50 text-red-900',
  xero_only_unknown: 'bg-red-50 text-red-900',
  xero_only_salaried: '',
  jm_only: '',
}

/**
 * DocketWorks holds both a loaded wage and a base wage: the loaded one is what
 * a job is charged, the base one is what the employee is paid. Xero pays the
 * base wage, so base is what reconciles — but the payroll pages let you switch,
 * and this one keeps that habit.
 *
 * Presentation only: both figures are already on the row, so the toggle costs
 * no request and cannot disagree with the server about which is which.
 */
function ourDollars(row: PayrollStaffWeekRowOut, wageBasis: WageBasis): number {
  return wageBasis === 'base' ? row.jm_base_pay : row.jm_cost
}

export type WageBasis = 'base' | 'loaded'

export interface PayrollReconciliationSearch {
  week?: string
  basis?: WageBasis
}

/** The week (Monday-snapped, as the weekly page reads it) and the wage basis, off the URL. */
export function payrollReconciliationSearchFromUrl(
  search: Record<string, unknown>,
): PayrollReconciliationSearch {
  return {
    ...weeklySearchFromUrl(search),
    basis: search.basis === 'base' || search.basis === 'loaded' ? search.basis : undefined,
  }
}

export interface PayrollReconciliationPageProps {
  weekStart: string
  /** Base by default (the route writes it): this page exists to be compared
      with Xero, and Xero pays the base wage. In the URL rather than page
      state so a shared link shows the same column (docs/design-language.md). */
  wageBasis: WageBasis
  onWageBasisChange: (basis: WageBasis) => void
}

export function PayrollReconciliationPage({
  weekStart,
  wageBasis,
  onWageBasisChange,
}: PayrollReconciliationPageProps) {
  const report = useQuery(
    accountingReportsPayrollWeekReconciliationRetrieveOptions({
      query: { week_start_date: weekStart },
    }),
  )

  const week = report.data?.week
  const rows = week?.staff
  // Both totals come from the server, like every other figure on this page. The
  // base column is what each row's status is judged on, so re-summing it here
  // made the headline total a second computation of a business value the
  // backend already owns (ADR 0020).
  const totalOurs =
    wageBasis === 'base' ? (week?.totals.jm_base_pay ?? 0) : (week?.totals.jm_cost ?? 0)
  const totalXero = week?.totals.xero_gross ?? 0

  return (
    <div className="min-h-screen p-6">
      <h1
        className="text-xl font-bold text-gray-900"
        data-automation-id="PayrollReconciliation-title"
      >
        Payroll reconciliation — week of {formatDate(weekStart)}
      </h1>

      <div className="mt-3 flex items-center gap-2 text-sm">
        <span className="text-gray-500">DocketWorks wages:</span>
        <SegmentedToggle
          value={wageBasis}
          options={[
            { value: 'base', label: 'Base' },
            { value: 'loaded', label: 'Loaded' },
          ]}
          automationPrefix="PayrollReconciliation-wageBasis"
          onChange={onWageBasisChange}
        />
        {wageBasis === 'loaded' && (
          <span className="text-amber-800" data-automation-id="PayrollReconciliation-loadedNote">
            Loaded wages allocate paid non-worked time to worked hours, while this week&rsquo;s Xero
            gross does not — the difference column is not a reconciliation in this mode.
          </span>
        )}
      </div>

      {report.data?.xero_source === 'live_run' && (
        <p
          className="mt-2 text-sm text-gray-500"
          data-automation-id="PayrollReconciliation-liveRunNote"
        >
          Figures are read live from the week&rsquo;s pay run. Xero recalculates a Draft&rsquo;s pay
          for a couple of minutes after a post, so a difference seen immediately after posting may
          still be settling &mdash; re-check before acting on it.
        </p>
      )}
      {report.data?.xero_source === 'no_pay_run' && (
        <p
          className="mt-2 text-sm text-amber-800"
          data-automation-id="PayrollReconciliation-noPayRun"
        >
          Xero has no pay run for this week yet, so there is nothing to compare against. Any
          difference below is that absence, not a finding.
        </p>
      )}

      <ListTable
        isPending={report.isPending}
        isError={report.isError}
        onRetry={() => void report.refetch()}
        loadingLabel="Asking Xero what it computed for this week..."
        loadingAutomationId="PayrollReconciliation-loading"
        errorLabel="Could not read the payroll reconciliation."
        rows={rows}
        emptyLabel="No staff and no pay slips for this week"
        automationId="PayrollReconciliation-table"
        head={
          <tr className="border-b border-gray-200 text-left text-gray-500">
            <th className="px-3 py-2">Staff</th>
            <th className="px-3 py-2 text-right">DocketWorks</th>
            <th className="px-3 py-2 text-right">Xero</th>
            <th className="px-3 py-2 text-right">Difference</th>
            <th className="px-3 py-2 text-right">Our hours</th>
            <th className="px-3 py-2 text-right">Xero hours</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        }
        renderRow={(row) => (
          <tr
            key={row.key}
            className={`border-b border-gray-100 ${ROW_TONE[row.status]}`}
            data-automation-id={`PayrollReconciliation-row-${row.status}`}
          >
            <td className="px-3 py-2">{row.name}</td>
            <td className="px-3 py-2 text-right">{formatCurrency(ourDollars(row, wageBasis))}</td>
            <td className="px-3 py-2 text-right">{formatCurrency(row.xero_gross)}</td>
            <td className="px-3 py-2 text-right font-medium">{formatCurrency(row.pay_diff)}</td>
            <td className="px-3 py-2 text-right">{row.jm_hours}</td>
            <td className="px-3 py-2 text-right">{row.xero_hours}</td>
            <td className="px-3 py-2">{STATUS_WORDING[row.status]}</td>
          </tr>
        )}
      >
        {week && (
          <div
            data-automation-id="PayrollReconciliation-summary-cards"
            className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3"
          >
            <SummaryCard
              label={wageBasis === 'base' ? 'DocketWorks base wages' : 'DocketWorks loaded wages'}
              valueAutomationId="PayrollReconciliation-total-ours"
            >
              {formatCurrency(totalOurs)}
            </SummaryCard>
            <SummaryCard label="Xero computed" valueAutomationId="PayrollReconciliation-total-xero">
              {formatCurrency(totalXero)}
            </SummaryCard>
            <SummaryCard
              label="Paid but not posted"
              valueAutomationId="PayrollReconciliation-unposted-count"
            >
              {report.data?.unposted_count ?? 0}
            </SummaryCard>
          </div>
        )}
      </ListTable>
    </div>
  )
}
