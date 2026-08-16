import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { mondayOf } from '@/lib/dates'
import { formatDate, localIsoDate } from '@/lib/format'

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

  // Three states, not two. Until the read resolves nothing here is
  // authoritative — `payRun` is undefined so the state reads "missing" and
  // `postableWeekStart` is null — and together those rendered an ENABLED
  // Create button that could race the read and try to create a run for a week
  // that already has one.
  //
  // A LOADED null is the server saying it cannot name the postable week (the
  // provider read failed). Its documented contract is to fall back to the
  // current week, so it authorises that one week — not, as before, every week
  // the operator happens to select.
  const currentWeek = mondayOf(localIsoDate())
  const isPostableWeek =
    !payroll.isLoading &&
    (postableWeekStart === null ? weekStart === currentWeek : postableWeekStart === weekStart)
  const busy = isPosting || payroll.isCreating || payroll.isRefreshing || payroll.isLoading

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
          {payroll.isLoading ? 'Reading pay runs from Xero…' : PAY_RUN_WORDING[payRunState]}
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

      {!isPostableWeek && !payroll.isLoading && (
        <p
          className="rounded bg-amber-50 p-2 text-xs text-amber-900"
          data-automation-id="PayrollPanel-notPostable"
        >
          Xero processes pay runs in order, so only the week starting{' '}
          {formatDate(postableWeekStart ?? currentWeek)} can be posted next.
          {postableWeekStart === null &&
            ' Xero could not be asked which week is next, so this is the current week.'}
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
        <Button
          variant="outline"
          size="sm"
          disabled={busy || payroll.isCheckingXero}
          title="Ask Xero what it holds for each staff member this week"
          data-automation-id="PayrollPanel-checkXero"
          onClick={payroll.checkXero}
        >
          {payroll.isCheckingXero ? 'Checking Xero…' : 'Check against Xero'}
        </Button>
        {isPosting && <Loader2 className="h-4 w-4 animate-spin text-slate-500" />}
      </div>

      <XeroReconciliation payroll={payroll} />

      {payroll.results.length > 0 && <PostResults results={payroll.results} />}
    </section>
  )
}

/**
 * What Xero holds for the week, against what the timesheet recorded.
 *
 * The panel's other figures come from the posting run, which only reports the
 * staff posted in THIS session. This is the standing answer: it survives a
 * reload, and it is what catches hours edited after a post — the case where
 * everything on screen looks posted and Xero is a day behind.
 *
 * Renders nothing until asked. Xero has no bulk leave endpoint, so the read
 * costs an API call per staff member; an unasked-for one on every visit to the
 * weekly grid would spend most of a minute of Xero's quota to answer a question
 * nobody asked.
 */
function XeroReconciliation({ payroll }: { payroll: UsePayrollWeekResult }) {
  if (payroll.isCheckingXero) {
    return (
      <p className="text-xs text-slate-500" data-automation-id="PayrollPanel-checkingXero">
        Asking Xero what it holds for each staff member…
      </p>
    )
  }
  if (payroll.postingStatusFailed) {
    return (
      <p className="text-xs text-amber-800" data-automation-id="PayrollPanel-statusUnavailable">
        Could not read what Xero holds for this week. The hours below are what DocketWorks recorded,
        not what Xero has.
      </p>
    )
  }
  const status = payroll.postingStatus
  if (status === undefined) return null

  const outOfSync = status.filter((row) => !row.matches)
  if (outOfSync.length === 0) {
    return (
      <p className="text-xs text-slate-600" data-automation-id="PayrollPanel-inSync">
        {/* Deliberately says WHICH staff were compared. These are the staff
            DocketWorks lists; it cannot yet see a Xero employee we posted
            nothing for, and Xero pays those their default pay-template hours —
            typically a full week nobody worked. Wording that implied "Xero is
            correct" would be reassurance covering the costliest case. */}
        Xero matches the timesheet for all {status.length} staff shown here. It does not check for
        Xero employees missing from this list, who would be paid their default hours.
      </p>
    )
  }
  return (
    <ul className="flex flex-col gap-1 text-xs" data-automation-id="PayrollPanel-outOfSync">
      {outOfSync.map((row) => (
        <li
          key={row.staff_id}
          className="text-amber-800"
          data-automation-id={`PayrollPanel-outOfSync-${row.staff_id}`}
        >
          {/* Both surfaces are named because they are posted through different
              Xero APIs: only leave debits a leave balance, so "3h short" means
              something different on each. */}
          Xero holds {row.posted_timesheet_hours}h worked and {row.posted_leave_hours}h leave; the
          timesheet records {row.recorded_timesheet_hours}h worked and {row.recorded_leave_hours}h
          leave.
        </li>
      ))}
    </ul>
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
  // Ordered by which blocker the operator can actually act on. "Create pay run
  // first" used to win over "not the postable week", so a week that could not
  // have a pay run at all was reported as merely lacking one — advice for an
  // action the panel does not even offer here, since Create is hidden off the
  // postable week.
  if (!isPostableWeek) return 'This is not the next postable week'
  if (payRunState === 'missing') return 'Create pay run first'
  if (payRunState === 'posted') return 'This week is locked'
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
