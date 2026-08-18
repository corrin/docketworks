import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import {
  accountingReportsPayrollWeekReconciliationRetrieveOptions,
  type PayrollStaffWeekRowOut,
} from '@/api'
import { ListTable } from '@/features/shared/ListTable'
import { formatCurrency } from '@/lib/format'
import { SummaryCard } from './SummaryCard'

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

const STATUS_WORDING: Record<string, string> = {
  ok: 'Matches',
  mismatch: 'Differs',
  xero_only_departed: 'Left — Xero is still paying them',
  xero_only_unposted: 'Paid, but no hours were posted',
  xero_only_unknown: 'Paid, but DocketWorks has no record',
  xero_only_salaried: 'Salaried — hours are job allocation only',
  jm_only: 'No pay slip',
}

/** The rows an operator has to act on. Salaried staff are expected, not a gap. */
const UNPOSTED_FINDINGS = new Set(['xero_only_departed', 'xero_only_unposted', 'xero_only_unknown'])

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

type WageBasis = 'base' | 'loaded'

function rowTone(status: string): string {
  if (status === 'xero_only_departed') return 'bg-red-50 text-red-900'
  if (status === 'xero_only_unknown') return 'bg-red-50 text-red-900'
  if (status === 'xero_only_unposted') return 'bg-red-50 text-red-900'
  if (status === 'mismatch') return 'text-amber-900'
  return ''
}

export function PayrollReconciliationPage({ weekStart }: { weekStart: string }) {
  // Base by default: this page exists to be compared with Xero, and Xero pays
  // the base wage.
  const [wageBasis, setWageBasis] = useState<WageBasis>('base')
  const report = useQuery(
    accountingReportsPayrollWeekReconciliationRetrieveOptions({
      query: { week_start_date: weekStart },
    }),
  )

  const week = report.data?.week
  const rows = week?.staff
  const unposted = (rows ?? []).filter((row) => UNPOSTED_FINDINGS.has(row.status))
  const totalOurs = (rows ?? []).reduce((sum, row) => sum + ourDollars(row, wageBasis), 0)
  const totalXero = week?.totals.xero_gross ?? 0

  return (
    <div className="min-h-screen p-6">
      <h1
        className="text-xl font-bold text-gray-900"
        data-automation-id="PayrollReconciliation-title"
      >
        Payroll reconciliation — week of {weekStart}
      </h1>

      <div className="mt-3 flex items-center gap-2 text-sm">
        <span className="text-gray-500">DocketWorks wages:</span>
        {(['base', 'loaded'] as const).map((basis) => (
          <button
            key={basis}
            type="button"
            onClick={() => setWageBasis(basis)}
            aria-pressed={wageBasis === basis}
            className={
              wageBasis === basis
                ? 'rounded bg-slate-800 px-2 py-1 text-white'
                : 'rounded border border-slate-300 px-2 py-1 text-slate-700'
            }
            data-automation-id={`PayrollReconciliation-wageBasis-${basis}`}
          >
            {basis === 'base' ? 'Base' : 'Loaded'}
          </button>
        ))}
        {wageBasis === 'loaded' && (
          <span className="text-amber-800" data-automation-id="PayrollReconciliation-loadedNote">
            Loaded wages carry the annual leave loading, which Xero does not pay — the difference
            column is not a reconciliation in this mode.
          </span>
        )}
      </div>

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
            key={row.name}
            className={`border-b border-gray-100 ${rowTone(row.status)}`}
            data-automation-id={`PayrollReconciliation-row-${row.status}`}
          >
            <td className="px-3 py-2">{row.name}</td>
            <td className="px-3 py-2 text-right">{formatCurrency(ourDollars(row, wageBasis))}</td>
            <td className="px-3 py-2 text-right">{formatCurrency(row.xero_gross)}</td>
            <td className="px-3 py-2 text-right font-medium">{formatCurrency(row.pay_diff)}</td>
            <td className="px-3 py-2 text-right">{row.jm_hours}</td>
            <td className="px-3 py-2 text-right">{row.xero_hours}</td>
            <td className="px-3 py-2">{STATUS_WORDING[row.status] ?? row.status}</td>
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
              {unposted.length}
            </SummaryCard>
          </div>
        )}
      </ListTable>
    </div>
  )
}
