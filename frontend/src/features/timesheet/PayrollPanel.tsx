import { Link } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import { i18n } from '@/lib/i18n'

import type { StaffWeekPostResultOut } from '@/api'
import type { UsePayrollWeekResult } from './usePayrollWeek'

/**
 * The payroll actions above the weekly grid: post the week, check against Xero.
 *
 * Fable: Two intents, two controls (plus the money link). The mechanics the
 * intents require — creating the Draft pay run, refreshing the pay-run mirror,
 * enforcing Xero's post-in-order rule — are the server's, done inside the POST
 * where they can be judged on fresh data. A "Create Pay Run" button invited
 * the operator to perform the one step whose early execution locks leave
 * changes (KAN-326), and a "Refresh from Xero" button made mirror hygiene the
 * operator's job.
 *
 * Opus: Deliberately outside QueryState: "no pay run for this week" is a real
 * state with its own wording, not an empty result — the binary pending/error
 * gate has no room for it, the same reason the Xero quote and invoice cards
 * sit outside it.
 */
export interface PayrollPanelProps {
  weekStart: string
  payroll: UsePayrollWeekResult
  /** Staff with hours the office has not approved this week. Posting pays
      approved time only, so these are named before the button is pressed. */
  heldBack: { staffId: string; name: string; hours: number }[]
  /** Navigate the page to another week (the banner's "Go to that week"). */
  onSelectWeek: (week: string) => void
}

export function PayrollPanel({ weekStart, payroll, heldBack, onSelectWeek }: PayrollPanelProps) {
  const { t } = useTranslation('timesheet')
  if (payroll.loadFailed) {
    // Opus: A failed read must not render as "no pay run exists" — the wording
    // below would then misdescribe a week that may already have one.
    return (
      <p className="rounded border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700">
        {t('payrollPanel.loadFailed')}
      </p>
    )
  }

  const { payRun, payRunState, postableWeekStart, isPosting, progress } = payroll

  // Fable: Advisory, not authoritative: it reads the mirror, which can be an
  // hour stale, so it informs rather than disables. The POST enforces the same
  // rule on a mirror it refreshes itself, so the worst a stale banner can cost
  // is a clear refusal naming the right week — never a wrong posting, and
  // never a truly-postable week locked behind stale data with no recovery.
  const offPostableWeek =
    !payroll.isLoading && postableWeekStart !== null && postableWeekStart !== weekStart
  const busy = isPosting || payroll.isLoading

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
          {payroll.isLoading ? t('payrollPanel.reading') : t(`payrollPanel.payRun.${payRunState}`)}
        </span>
        {payRun && (
          <span className="text-xs text-slate-600">
            {t('payrollPanel.paid', { date: formatDate(payRun.payment_date) })}
          </span>
        )}
        {payRun && (
          <a
            className="text-xs text-blue-700 underline"
            href={payRun.xero_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t('payrollPanel.openInXero')}
          </a>
        )}
      </div>

      {offPostableWeek && (
        <p
          className="rounded bg-amber-50 p-2 text-xs text-amber-900"
          data-automation-id="PayrollPanel-notPostable"
        >
          {t('payrollPanel.notPostable', { date: formatDate(postableWeekStart ?? weekStart) })}{' '}
          <button
            type="button"
            className="font-medium text-amber-900 underline underline-offset-2"
            data-automation-id="PayrollPanel-goToPostableWeek"
            onClick={() => onSelectWeek(postableWeekStart ?? weekStart)}
          >
            {t('payrollPanel.goToWeek')}
          </button>
        </p>
      )}

      {heldBack.length > 0 && (
        <p
          className="rounded bg-amber-50 p-2 text-xs text-amber-900"
          data-automation-id="PayrollPanel-heldBack"
        >
          {t('payrollPanel.heldBack', {
            list: heldBack
              .map((row) => t('payrollPanel.heldBackRow', { name: row.name, hours: row.hours }))
              .join(', '),
          })}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {/* Opus: Deliberately NOT gated on a draft pay run existing. Posting
            reconciles leave BEFORE it creates the pay run, because Xero locks
            leave changes once the employee is in a draft (KAN-326) — so
            requiring a draft first defeated that ordering on every post, and
            made the backend's sequencing unreachable through this screen. It
            also deadlocked: the error tells the operator to delete the draft,
            which then disabled the only button that could recover. Posting
            calls ensure_pay_run_for_week itself, so "missing" is postable. */}
        <Button
          size="sm"
          className="bg-orange-600 text-white hover:bg-orange-700 disabled:opacity-50"
          disabled={busy || payRunState === 'posted'}
          title={postButtonTitle(payRunState)}
          data-automation-id="PayrollPanel-postAll"
          onClick={() => payroll.postWeek()}
        >
          {postButtonLabel(payroll, progress)}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={busy || payroll.isCheckingXero}
          title={t('payrollPanel.checkXeroTitle')}
          data-automation-id="PayrollPanel-checkXero"
          onClick={payroll.checkXero}
        >
          {payroll.isCheckingXero ? t('payrollPanel.checkingXero') : t('payrollPanel.checkXero')}
        </Button>
        {/* A link, not a redirect after posting: the per-staff results below
            live in session state and any navigation wipes them, so the
            operator chooses when to leave them. */}
        <Link
          to="/reports/payroll-reconciliation"
          search={{ week: weekStart }}
          className="text-sm font-medium text-blue-700 underline underline-offset-2"
          title={t('payrollPanel.checkMoneyTitle')}
          data-automation-id="PayrollPanel-checkTheMoney"
        >
          {t('payrollPanel.checkMoney')}
        </Link>
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
 * Opus: The panel's other figures come from the posting run, which only reports the
 * staff posted in THIS session. This is the standing answer: it survives a
 * reload, and it is what catches hours edited after a post — the case where
 * everything on screen looks posted and Xero is a day behind.
 *
 * Opus: Renders nothing until asked. Xero has no bulk leave endpoint, so the read
 * costs an API call per staff member; an unasked-for one on every visit to the
 * weekly grid would spend most of a minute of Xero's quota to answer a question
 * nobody asked.
 */
function XeroReconciliation({ payroll }: { payroll: UsePayrollWeekResult }) {
  const { t } = useTranslation('timesheet')
  if (payroll.isCheckingXero) {
    return (
      <p className="text-xs text-slate-500" data-automation-id="PayrollPanel-checkingXero">
        {t('payrollPanel.asking')}
      </p>
    )
  }
  if (payroll.postingStatusFailed) {
    return (
      <p className="text-xs text-amber-800" data-automation-id="PayrollPanel-statusUnavailable">
        {t('payrollPanel.statusUnavailable')}
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
        {t('payrollPanel.inSync', { staff: status.length })}
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
          {t('payrollPanel.outOfSync', {
            postedWork: row.posted_timesheet_hours,
            postedLeave: row.posted_leave_hours,
            recordedWork: row.recorded_timesheet_hours,
            recordedLeave: row.recorded_leave_hours,
          })}
        </li>
      ))}
    </ul>
  )
}

function postButtonLabel(
  payroll: UsePayrollWeekResult,
  progress: UsePayrollWeekResult['progress'],
): string {
  if (progress)
    return i18n.t('timesheet:payrollPanel.posting', {
      current: progress.current,
      total: progress.total,
    })
  if (payroll.hasPosted) return i18n.t('timesheet:payrollPanel.repost')
  return i18n.t('timesheet:payrollPanel.postAll')
}

function postButtonTitle(payRunState: string): string {
  if (payRunState === 'posted') return i18n.t('timesheet:payrollPanel.lockedTitle')
  // Opus: A missing pay run is no longer a blocker, so it must not read as one.
  // Posting creates the run itself, and must, because it reconciles leave first
  // and Xero locks leave once the employee is in a draft (KAN-326).
  if (payRunState === 'missing') {
    return i18n.t('timesheet:payrollPanel.postCreatingTitle')
  }
  return i18n.t('timesheet:payrollPanel.postTitle')
}

function PostResults({ results }: { results: StaffWeekPostResultOut[] }) {
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

function resultTone(result: StaffWeekPostResultOut): string {
  if (!result.success) return 'text-red-700'
  if (result.skipped) return 'text-amber-800'
  return 'text-slate-600'
}

function resultText(result: StaffWeekPostResultOut): string {
  if (!result.success) return result.error ?? i18n.t('timesheet:payrollPanel.result.failed')
  if (result.posting_mode === 'salary') {
    const cleanup = result.salary_timesheet_removed
      ? i18n.t('timesheet:payrollPanel.result.timesheetRemoved')
      : ''
    return `${result.reason ?? i18n.t('timesheet:payrollPanel.result.salary')}${cleanup}`
  }
  if (result.skipped) {
    const reason = result.reason ?? i18n.t('timesheet:payrollPanel.result.notPosted')
    // Opus: Hours that exist but were deliberately not posted are the case an
    // operator must not discover later by reconciling against Xero.
    return result.has_entries
      ? i18n.t('timesheet:payrollPanel.result.hoursNotPosted', { reason })
      : reason
  }
  // Opus: All three buckets ADR 0007 routes, not two. other_leave is paid leave that
  // goes through the Timesheets API rather than the Leave API, so omitting it
  // under-reported what had just been written to someone's pay.
  const otherLeave = result.other_leave_hours
    ? i18n.t('timesheet:payrollPanel.result.otherLeave', { hours: result.other_leave_hours })
    : ''
  return i18n.t('timesheet:payrollPanel.result.posted', {
    work: result.work_hours,
    leave: result.leave_hours,
    otherLeave,
  })
}
