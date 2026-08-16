# 0007 — Xero Payroll NZ sync with four-bucket hour categorisation

A week's time entries split into work / other-leave / annual-or-sick / unpaid buckets, each posted through the Xero surface that can actually represent it.

## Rules

- Posting a week runs in `apps/xero/payroll_push.py` and `payroll_leave.py`, reached from the
  domain layer through `apps/accounting/registry.get_provider()` (ADR 0012). `apps.xero` sits
  above the domain apps in the import contract, so `apps.timesheet` cannot call it directly —
  and the registry is also what swaps in the write-suppressing provider under `XERO_READONLY`.
- **The routing key is the line's own `CostLine.xero_pay_item`**, never the job's name or the
  job's default pay item. `XeroPayItem.uses_leave_api` selects the surface and `multiplier`
  distinguishes work from leave paid as an earnings rate:
  - **work** → Timesheets API, aggregated to one line per `(date, earnings_rate_id)`;
  - **other leave** (paid, no balance — an earnings rate) → Timesheets API;
  - **annual / sick and every other leave type** → Employee Leave API, the only surface that
    debits the leave balance;
  - **unpaid** → posted like any other line whose pay item says so, and surfaced in the result.
  A name match cannot answer this: "Holiday Pay" exists in Xero BOTH as an earnings rate and as
  a leave type.
- **Leave posts as ONE period spanning the payroll week**, carrying the total units. Verified
  live 2026-08-02 (KAN-326): per-day periods are accepted but their units are DISCARDED — Xero
  recomputes them from the employee's working pattern — and more than one period per pay period
  is rejected on update. The total is therefore the only figure that round-trips, and the only
  one leave can be matched on when reconciling.
- **The order of operations is load-bearing**: validate pay items → reconcile leave → ensure the
  Draft pay run → fetch every existing timesheet in one call → post per staff. Leave MUST be
  reconciled before the pay run exists, because Xero locks leave deletion once the employee is
  in a draft pay run. Leave *updates* are still permitted at that point, which is why the
  reconcile updates an overlapping stale request in place rather than deleting and recreating.
- Before posting work hours, delete the existing timesheet lines on Xero — re-posting replaces
  rather than appends, so Xero stays the single source of truth for what was posted. An
  unchanged re-post is detected (lines compared at `payroll_push.UNIT_PRECISION`, three
  decimal places, matching `payroll_leave.LEAVE_UNIT_PRECISION`) and skipped.
- An empty week still posts an empty timesheet. Without one Xero falls back to the employee's
  pay template, typically 40 hours. Xero rejects zero-unit lines but accepts an empty timesheet.
- `create_pay_run` mirrors the created run locally **even when Xero returns a different period
  than requested**, then fails. The run exists in Xero either way, and without the mirror row
  the next attempt hits Xero's one-draft-per-calendar refusal with no local trace of why.
- Earnings rates and leave types are synced into `XeroPayItem` by
  `python manage.py xero --configure-payroll` before first use.

## Do not

- **A local "posted" flag on CostLine** — any flag that can disagree with Xero's actual state
  eventually will; ask Xero instead. `week_posting_status` does exactly that, on its own
  endpoint so the weekly grid still renders when Xero is unreachable.
- **Post from the SSE stream.** The posting runs in a Celery task; the stream only replays the
  progress that task publishes. v1 did the Xero writing inside the stream's GET handler, which
  made fetching a URL write payroll — against this repo's first coding standard — and meant a
  client that disconnected mid-batch destroyed the only record of which staff had succeeded.
- **Pattern-match the job name to find leave.** v1's `Job.get_leave_type()` did, which made
  renaming a leave job silently reclassify paid leave, and left three separate leave rules free
  to drift apart.
