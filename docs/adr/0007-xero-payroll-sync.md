# 0007 — Xero Payroll NZ sync with four-bucket hour categorisation

Split a week's `CostLine` time entries into work / other-leave / annual-or-sick / unpaid buckets and post each through the right Xero surface, with Draft-pay-run gating and idempotent re-posting.

## Problem

Users record work and leave as `CostLine` entries (`kind='time'`). Xero Payroll NZ splits responsibility across two surfaces: **Timesheets** (work hours and paid leave that doesn't accrue balances, via earnings-rate IDs) and **Employee Leave** (annual/sick/balance-tracked leave, via leave-type IDs). Pay runs are immutable once `Posted` — a posted run is locked forever. So we need to know, per entry, which surface to use *and* we need re-posting to be safe in case the user edits the week and re-syncs.

## Decision

`PayrollSyncService.post_week_to_xero(staff_id, week_start_date)` categorises entries by `Job.get_leave_type()`:

- **work** → Timesheets API, mapping `wage_rate_multiplier → earnings_rate_id`.
- **other leave** (paid, no balance) → Timesheets API.
- **annual / sick** → Employee Leave API, grouping consecutive days into `LeavePeriod` objects.
- **unpaid** → discarded.

Before posting work hours, delete existing timesheet lines on Xero — so re-posting is replace-not-append. Before any posting, verify the pay run is `Draft`; fail fast if it's `Posted`. Earnings-rate IDs and leave-type IDs are stored on `CompanyDefaults` and seeded via `python manage.py xero --configure-payroll`.

## Why

Xero's two surfaces aren't a quirk — they're how balance-tracked leave actually works (it has to debit the leave balance, which a timesheet line can't do). Forcing one surface means losing balance tracking. Replace-not-append delegates source-of-truth to Xero rather than maintaining our own "posted" state that would drift. The Draft check is what stops a re-sync from silently failing against a locked pay run.

## Alternatives considered

- **Compute leave categories from job flags, not job name.** Defendable — names are mutable, flags are explicit. Rejected for now: `Job.get_leave_type()` returning a small string enum keeps the leave-type decision local to the job's identity and the existing leave jobs already encode this in the name. Revisit if a leave job ever gets renamed and breaks categorisation.
- **Track our own "posted" flag on the CostLine.** Defendable — avoids a Xero round-trip on re-sync. Rejected: any flag that can disagree with Xero's actual state will eventually disagree.

## Consequences

Week-level posting is a single service call; re-posting is safe; unpaid hours are dropped cleanly while still surfacing in the result for audit. `Job.get_leave_type()` pattern-matches on job name, so renaming a leave job silently breaks categorisation — needs tests. Seven new `CompanyDefaults` fields must be seeded before first use.
