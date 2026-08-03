# 0007 — Xero Payroll NZ sync with four-bucket hour categorisation

A week's time entries split into work / other-leave / annual-or-sick / unpaid buckets, each posted through the Xero surface that can actually represent it.

## Rules

- `PayrollSyncService.post_week_to_xero(staff_id, week_start_date)` categorises the week's `CostLine` time entries by `Job.get_leave_type()`:
  - **work** → Timesheets API, mapping `wage_rate_multiplier` → `earnings_rate_id`;
  - **other leave** (paid, no balance) → Timesheets API;
  - **annual / sick** → Employee Leave API, consecutive days grouped into `LeavePeriod`s — only that surface debits the leave balance, which a timesheet line cannot do;
  - **unpaid** → not posted, but surfaced in the result for audit.
- Before posting work hours, delete the existing timesheet lines on Xero — re-posting replaces rather than appends, so Xero stays the single source of truth for what was posted.
- Before posting anything, verify the pay run is `Draft` and fail fast if it is `Posted` — a posted run is locked forever, and without the check a re-sync fails silently.
- Earnings-rate and leave-type IDs live on `CompanyDefaults` (seven fields), seeded by `python manage.py xero --configure-payroll` before first use.
- `Job.get_leave_type()` pattern-matches the job name, so renaming a leave job silently breaks categorisation — keep that covered by tests.

## Do not

- **A local "posted" flag on CostLine** — any flag that can disagree with Xero's actual state eventually will; ask Xero instead.
