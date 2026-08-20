# Xero Payroll UI Requirements

**Status: built.** The page is `/timesheets/weekly`
(`src/features/timesheet/WeeklyOverviewPage.tsx` plus `PayrollPanel.tsx` and
`usePayrollWeek.ts`), and its E2E spec is
`tests/e2e/timesheet/weekly-payroll.spec.ts`, which posts a real week to Xero
and reads it back. This document remains the UI contract: it is what the page
is checked against, not a record of building it. The posting mechanism itself
(surfaces, ordering, irreversibility) is ADR 0007's, not this document's.

## The operator's intents

Two, plus a report:

1. **Post the week to Xero.** One button. Posting creates the Draft pay run
   itself (leave must reconcile before the draft exists — KAN-326), replaces
   any previously posted lines, and reports per-staff results as they happen.
2. **Check against Xero.** Ask what Xero actually holds for the week, per
   staff member, hours split by surface.
3. **Check the money.** A link to `/reports/payroll-reconciliation?week=<monday>`,
   which compares what DocketWorks expects Xero to pay against what Xero
   computed.

Everything else the integration requires — creating the pay run, refreshing
the pay-run mirror, enforcing Xero's post-in-order rule, choosing the roster —
is the server's, done inside the POST where it can be judged on fresh data.
The UI must not grow controls for those steps; that was tried, and it handed
the operator the one step (early draft creation) that locks leave changes.

## Wire contract

All payroll operations are on the timesheet router (`apps/timesheet/api.py`),
superuser-only, consumed through the generated TanStack Query layer:

- `GET /api/timesheets/payroll/pay-runs/` — the mirror's pay runs plus
  `next_postable_week_start_date`/`_end_date`. The postable week is advisory
  here (the mirror refreshes hourly); null means the server cannot name one,
  and the client renders no banner and invents nothing — it never computes a
  week from its own clock.
- `POST /api/timesheets/payroll/post-staff-week/` — body is
  `{week_start_date}` only. The server derives the roster (the same
  `get_displayable_staff` filter the grid uses), refreshes the mirror,
  refuses a non-postable week with a 400 naming the postable one, refuses a
  week already being posted with a 409 naming the live run, and answers the
  run's opening document `{run: ...}`.
- `GET /api/timesheets/payroll/runs/` and the SSE stream at
  `api/timesheets/payroll/runs/stream/` (ADR 0047) — the same run document,
  polled and pushed. Every push carries the whole document, so reconnecting
  or reloading needs the present, not a replayed history.
- `GET /api/timesheets/payroll/week-status/` — what Xero holds for the week.
  Never called on page load: it costs one Xero call per staff member.
  "Check against Xero" asks for it, and a completed posting run asks for it.

## Page behaviour

- **Landing:** a bare `/timesheets/weekly` lands on the server-named postable
  week; an explicit `?week=` is the operator's choice and is never overridden.
- **Pay-run state** renders in words ("Pay run ready for posting", "Pay run
  locked (already paid)", "Pay run not created yet") — never an icon alone.
- **Post** is disabled only while reads are in flight, while a run is live, or
  when the week is locked (Posted). Off the postable week it stays enabled and
  the banner advises, with "Go to that week"; the server's refusal is the
  enforcement, and a stale banner must never lock the truly-postable week
  behind a disabled control.
- **Progress and results** come from the run document ("Posting 3 of 10…",
  then per-staff rows). Failed staff keep an actionable message; hours that
  exist but were deliberately not posted say so. Results survive reload and
  reconnect (the document is server-held); navigation away is the operator's
  choice, which is why "Check the money" is a link, not a redirect.
- **Errors** are the backend's messages verbatim (ADR 0038), which name the
  fix — "delete the draft pay run for …, then post again".
- The panel answers in **hours**; the money question is the reconciliation
  page, which compares `jm_base_pay` (the loading removed) against Xero's
  gross — the loaded wage is what a job is charged, not what Xero pays, and
  the page's Base/Loaded toggle is presentation over figures already on the
  row.

## Testing checklist (the E2E spec's shape)

- Posting on the postable week succeeds with no pay run existing beforehand,
  and drives the SSE progress UI to per-staff results.
- Posting out of order is refused by the server with the postable week named,
  no run started.
- Re-posting after an hours edit replaces rather than appends, verified
  against Xero's own records.
- Week navigation moves the grid and the panel together.
- Xero fidelity: real demo-company objects, opt-in for the posting writes
  (`@xero-payroll-write`), cleaned per
  [`e2e-testing-strategy.md`](e2e-testing-strategy.md).
