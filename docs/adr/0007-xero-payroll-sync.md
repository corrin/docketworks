# 0007 — Xero Payroll NZ sync with four-bucket hour categorisation

Split a week's `CostLine` time entries into work / other-leave / annual-or-sick / unpaid buckets and post each through the right Xero surface (Timesheets API or Employee Leave API), with Draft-pay-run gating and idempotent re-posting.

- **Status:** Accepted (backend; frontend/REST endpoints deferred)
- **Date:** 2025-11-04
- **PR(s):** Commit `84a19d12` — feat(xero-payroll): complete backend implementation with pay run creation and testing (predates GitHub PR workflow)

## Context

Users record work and leave as `CostLine` entries (`kind='time'`, `meta['wage_rate_multiplier']`, job name pattern-matching leave type). We want to post a whole week's hours to Xero Payroll NZ. The Xero Payroll NZ API splits responsibility across two surfaces: **Timesheets** (work hours, paid leave that doesn't accrue balances, via earnings-rate IDs) and **Employee Leave** (annual/sick/balance-tracked leave, via leave-type IDs). Pay runs must be created in `Draft` state *before* hours can be posted; a `Posted` pay run is locked forever.

## Decision

Implement as a service layer (no REST/UI yet). `PayrollSyncService.post_week_to_xero(staff_id, week_start_date)` categorises the week's `CostLine`s into four buckets by `Job.get_leave_type()`: **work** → Timesheets API with `wage_rate_multiplier → earnings_rate_id` mapping; **other leave** (paid, no balance) → Timesheets API; **annual/sick** → Employee Leave API, grouping consecutive days into `LeavePeriod` objects; **unpaid** → discarded (no posting). Before posting work hours, delete existing timesheet lines to make re-posting idempotent. Before any posting, verify the pay run is `Draft` (not `Posted`) and fail fast with a clear error if locked. Leave-type IDs and earnings-rate IDs are stored on `CompanyDefaults` (seven new fields) and seeded via `python manage.py xero --configure-payroll`.

## Alternatives considered

- **Single API surface:** Xero doesn't offer one; balance-tracked leave and timesheet lines are genuinely different resources. Forcing one-fits-all would require posting leave as work hours and losing the balance tracking.
- **Compute categories on the fly from job flags:** less visible than `Job.get_leave_type()` returning a small string enum; pattern-matching the job name keeps the leave-type decision close to the job's identity.
- **Idempotency by tracking our own "posted" flag:** would drift from Xero's state. Deleting timesheet lines before re-posting delegates the source-of-truth to Xero.

## Consequences

- **Positive:** week-level posting is a single service call; re-posting is safe (replace-not-append); four-bucket split lets us drop unpaid hours cleanly while still surfacing them in the result dict for audit.
- **Negative / costs:** `Job.get_leave_type()` pattern-matches on job *name*, so renaming a leave job silently breaks categorisation — needs tests. Seven new `CompanyDefaults` fields must be seeded before first use. No REST endpoint yet: the feature is backend-only until UI work lands.
- **Follow-ups:** REST endpoint (`POST /api/timesheet/post-week-to-xero/`), frontend "Post week" button, `leave_type` field in the job serialiser, unit tests for `_categorize_entries`, `_map_work_entries`, `_post_leave_entries`.
