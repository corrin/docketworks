import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'

import type { PayrollCompleteEvent } from '@/api'
import type { UsePayrollWeekResult } from './usePayrollWeek'

/**
 * The pay-run and posting controls above the weekly grid.
 *
 * Deliberately outside QueryState: "no pay run for this week" is a real state
 * with its own offer (create one), not an empty result — the binary
 * pending/error gate has no room for it, the same reason the Xero quote and
 * invoice cards sit outside it.
 */
export interface PayrollPanelProps {
  weekStart: string
  payroll: UsePayrollWeekResult
  staffIds: string[]
}

const PAY_RUN_WORDING = {
  draft: 'Pay run ready for posting',
  posted: 'Pay run locked (already paid)',
  missing: 'Pay run not created yet',
} as const

export function PayrollPanel({ weekStart, payroll, staffIds }: PayrollPanelProps) {
  if (payroll.loadFailed) {
    // A failed read must not render as "no pay run exists" — that would offer
    // Create Pay Run for a week that may already have one.
    return (
      <p className="rounded border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700">
        Could not load pay runs from Xero. Reload the page.
      </p>
    )
  }

  const { payRun, payRunState, postableWeekStart, isPosting, progress } = payroll
  const isPostableWeek = postableWeekStart === null || postableWeekStart === weekStart
  const busy = isPosting || payroll.isCreating || payroll.isRefreshing

  return (
    <section
      className="flex flex-col gap-3 rounded border border-slate-200 bg-white p-3"
      data-automation-id="PayrollPanel"
    >
      <div className="flex flex-wrap items-center gap-3">
        <span
          className="text-sm font-semibold text-slate-800"
          data-automation-id="PayrollPanel-status"
        >
          {PAY_RUN_WORDING[payRunState]}
        </span>
        {payRun && (
          <span className="text-xs text-slate-600">Paid {formatDate(payRun.payment_date)}</span>
        )}
        {payRun && (
          <a
            className="text-xs text-blue-700 underline"
            href={payRun.xero_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in Xero
          </a>
        )}
      </div>

      {!isPostableWeek && (
        <p
          className="rounded bg-amber-50 p-2 text-xs text-amber-900"
          data-automation-id="PayrollPanel-notPostable"
        >
          Xero processes pay runs in order, so only the week starting{' '}
          {formatDate(postableWeekStart)} can be posted next.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {payRunState === 'missing' && isPostableWeek && (
          <Button
            size="sm"
            disabled={busy}
            data-automation-id="PayrollPanel-createPayRun"
            onClick={payroll.createPayRun}
          >
            {payroll.isCreating ? 'Creating…' : 'Create Pay Run for This Week'}
          </Button>
        )}
        <Button
          size="sm"
          className="bg-orange-600 text-white hover:bg-orange-700 disabled:opacity-50"
          disabled={busy || payRunState !== 'draft' || !isPostableWeek}
          title={postButtonTitle(payRunState, isPostableWeek)}
          data-automation-id="PayrollPanel-postAll"
          onClick={() => payroll.postWeek(staffIds)}
        >
          {postButtonLabel(payroll, progress)}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          data-automation-id="PayrollPanel-refresh"
          onClick={payroll.refreshPayRuns}
        >
          {payroll.isRefreshing ? 'Refreshing…' : 'Refresh from Xero'}
        </Button>
        {isPosting && <Loader2 className="h-4 w-4 animate-spin text-slate-500" />}
      </div>

      {payroll.results.length > 0 && <PostResults results={payroll.results} />}
    </section>
  )
}

function postButtonLabel(
  payroll: UsePayrollWeekResult,
  progress: UsePayrollWeekResult['progress'],
): string {
  if (progress) return `Posting ${progress.current} of ${progress.total}…`
  if (payroll.hasPosted) return 'Re-post to Xero'
  return 'Post All Staff to Xero'
}

function postButtonTitle(payRunState: string, isPostableWeek: boolean): string {
  if (payRunState === 'missing') return 'Create pay run first'
  if (payRunState === 'posted') return 'This week is locked'
  if (!isPostableWeek) return 'This is not the next postable week'
  return 'Post every staff member’s hours for this week to Xero'
}

function PostResults({ results }: { results: PayrollCompleteEvent[] }) {
  return (
    <ul className="flex flex-col gap-1 text-xs" data-automation-id="PayrollPanel-results">
      {results.map((result) => (
        <li
          key={result.staff_id}
          className={resultTone(result)}
          data-automation-id={`PayrollPanel-result-${result.staff_id}`}
        >
          <span className="font-medium">{result.staff_name}</span> — {resultText(result)}
        </li>
      ))}
    </ul>
  )
}

function resultTone(result: PayrollCompleteEvent): string {
  if (!result.success) return 'text-red-700'
  if (result.skipped) return 'text-amber-800'
  return 'text-slate-600'
}

function resultText(result: PayrollCompleteEvent): string {
  if (!result.success) return result.error ?? 'Failed to post'
  if (result.skipped) {
    const reason = result.reason ?? 'not posted'
    // Hours that exist but were deliberately not posted are the case an
    // operator must not discover later by reconciling against Xero.
    return result.has_entries ? `${reason} — hours NOT posted to Xero` : reason
  }
  return `posted ${result.work_hours}h work, ${result.leave_hours}h leave`
}
