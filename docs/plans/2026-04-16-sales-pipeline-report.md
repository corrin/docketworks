# Sales Pipeline Report V1

## Summary

Build a full `Sales Pipeline Report` that answers one primary question: is enough approved work flowing into the shop, and if not, where is the bottleneck? The report must be reproducible historically as of `end_date`, with "today" as the default case. Keep the first implementation focused on one backend endpoint and one frontend report view, but include all 5 report sections from the draft:

- Scoreboard
- Pipeline Snapshot
- Velocity
- Conversion Funnel
- Trend

Use existing report patterns for API/view wiring and existing `JobEvent`, `Job`, and CostSet summary data for metrics. Do not expand scope to rework event storage now; isolate transition parsing in one service layer so it can be swapped to structured JobEvents when the separate PR lands.

## Key Changes

### Backend behavior

Create `SalesPipelineService` under `apps/accounting/services/` and make it the only place that computes report metrics. Views and serializers stay thin.

Add one API endpoint:

- `GET /api/accounting/reports/sales-pipeline/`

Request params:

- `start_date` required
- `end_date` optional, default `today`
- `rolling_window_weeks` optional, default `4`
- `trend_weeks` optional, default `13`

Fail early at request validation:

- reject missing/invalid `start_date` with `400`
- default missing `end_date` to `today`
- reject invalid `end_date` with `400`
- reject `start_date > end_date` with `400`
- reject non-positive `rolling_window_weeks` or `trend_weeks` with `400`

Add `daily_approved_hours_target` to `CompanyDefaults` because this is a reusable business threshold, not frontend-only state.

### Metric definitions

Implement explicit, stable rules for each section:

- Scoreboard:
  - `approved_hours_total` = hours from jobs whose first qualifying transition into `approved` or `in_progress` occurs within the period
  - prefer `latest_quote.summary["hours"]`; if absent, use `latest_estimate.summary["hours"]`
  - direct jobs are jobs counted here without a quote-sent transition
  - count each job at most once per reporting period

- Pipeline Snapshot:
  - snapshot as of `end_date`, for jobs historically in `draft` or `awaiting_approval` at that cutoff
  - derive stage membership from historical job state as of `end_date`, not current `job.status`
  - draft hours/value come from `latest_estimate.summary`
  - awaiting-approval hours/value come from `latest_quote.summary`
  - days in stage come from the most recent status-change event that moved the job into that stage before `end_date`

- Velocity:
  - draft to quote-sent = `created_at` to first transition into `awaiting_approval`
  - quote-sent to resolved = first `awaiting_approval` to first `approved` or `job_rejected`
  - created to approved = `created_at` to first qualifying approval transition
  - report median, p80, and sample size only

- Conversion Funnel:
  - based on jobs created in the reporting period
  - compute both job counts and hours
  - quote-stage hours use quote summary; draft/direct-only hours use estimate summary
  - accepted/rejected/waiting/direct/still-draft categories must be mutually exclusive

- Trend:
  - weekly buckets over the lookback window
  - each week includes approved hours, approved hours per working day, acceptance rate by hours, pipeline hours as of week-end, and median velocity days
  - rolling-average output is derived from the same weekly series, not recomputed from a separate query path

### Transition/event handling

For now, keep transition detection simple and compatible with the current schema:

- use `JobEvent` with `event_type="status_changed"` and current description text matching
- centralize all matching/parsing in one helper module or private service methods
- document the exact strings treated as:
  - quote sent
  - approved
  - in progress
  - rejected
- dedupe by job and metric-specific "first qualifying event" rules
- add a note in the plan and code that this helper is temporary and should be replaced by structured event fields once that PR merges

For historical state:

- derive as-of stage membership from job history / status transition history at `end_date`
- do not use live `job.status` for historical snapshots or historical weekly trend points
- if historical state cannot be resolved for a job, exclude it from the affected section and emit a warning

### Unhappy-path and data-quality handling

Do not silently invent values.

If a job needed for a metric has missing or inconsistent summary/event data:

- persist the exception with `persist_app_error(...)`
- exclude that job from the affected metric or section
- continue building the report
- include warning metadata in the response, at minimum:
  - warning count
  - affected section(s)
  - job ids / job numbers for up to a small capped sample
  - a machine-readable warning code such as `missing_hours_summary` or `missing_stage_transition`

Abort the whole report only for request-level or system-level failures, such as invalid params, broken query construction, or unexpected unhandled exceptions.

For historical quote/estimate values in v1:

- use the job's current `latest_quote` / `latest_estimate` summaries as the value source
- treat this as an intentional v1 proxy for historical snapshot hours/value while historical job state remains the primary concern
- document that this is expected to be accurate for most jobs, but can drift if quotes or estimates were revised after the historical cutoff
- if neither summary can provide required hours/value, exclude the job from the affected metric and warn

### DRY and implementation structure

Avoid five separate ad hoc query implementations. Structure the service around reusable helpers:

- query/validate working-day inputs
- fetch target from `CompanyDefaults`
- fetch/categorize relevant `JobEvents`
- resolve historical stage membership as of a cutoff date
- resolve job hours/value from quote/estimate summaries
- compute working days using existing accounting working-day logic
- build warnings consistently across sections

Reuse existing report API/view patterns from accounting reports for serializer validation, standard error responses, and `AlreadyLoggedException` handling.

## Response Shape / Interfaces

Return one response object with these top-level sections:

- `period`
- `scoreboard`
- `pipeline_snapshot`
- `velocity`
- `conversion_funnel`
- `trend`
- `warnings`

Add serializers for:

- query params
- each report section
- warning rows / warning summary

Keep the warning contract explicit so the frontend can show "report generated with exclusions" instead of pretending the data is complete.

## Frontend

Create one report view and one service using existing report conventions.

The v1 page should show:

- scoreboard cards
- pipeline snapshot table
- velocity cards plus stale deals list
- conversion funnel visualization
- weekly trend chart
- date range picker and rolling-window selector
- visible warning banner when exclusions occurred

Do not add extra frontend-only business logic. The backend owns all metric calculations and warning classification.

## Test Plan

Add automated tests at the service layer first, then a smaller set of API tests.

Service-level tests should cover:

- request period logic with omitted `end_date` defaulting to today
- transition parsing and dedupe rules
- job approved then moved to `in_progress` in the same period counts once
- direct-approved jobs appear in approved-hours totals and direct bucket
- funnel categorization is mutually exclusive
- historical snapshot stage membership is resolved as of `end_date`, not from current live status
- days-in-stage uses the most recent transition into the stage before `end_date`
- velocity median, p80, and sample size are correct from known fixture data
- weekly trend points and rolling average are derived from the same underlying weekly series
- working-days divisor matches existing accounting working-day logic
- missing quote/estimate summary excludes only affected rows and emits warnings
- missing/malformed `JobEvent` history excludes affected rows from velocity, funnel, or snapshot and emits warnings
- changing `CompanyDefaults.daily_approved_hours_target` changes scoreboard target output

API tests should cover:

- valid request returns all top-level sections plus `warnings`
- omitted `end_date` defaults to today in the response period metadata
- invalid/missing `start_date` returns `400`
- invalid `end_date` returns `400`
- `start_date > end_date` returns `400`
- invalid `rolling_window_weeks` / `trend_weeks` returns `400`
- unexpected failures return the standard error shape

Manual validation must cover:

- today-mode run with a mixed period of quoted and direct jobs
- historical run for a prior period and comparison against today
- a job that is currently archived but was in draft or awaiting approval at the historical `end_date` appears correctly in the historical snapshot
- a job approved in the past period but later moved again still counts once in the correct historical period
- snapshot totals align with the jobs shown for `draft` and `awaiting_approval`
- one deliberately broken job summary or transition history produces warnings without breaking the whole report
- frontend renders the warning banner, all five sections, and the default-today behavior correctly

## Assumptions

- The separate structured-JobEvent PR will land soon, so this report may temporarily rely on description matching, but that logic must be isolated for easy replacement.
- `latest_quote.summary` and `latest_estimate.summary` are acceptable v1 sources for pipeline hours/value when present.
- Historical snapshot hours/value in v1 use the latest attached quote/estimate as a practical proxy; this should be accurate for most jobs but can drift after later revisions.
- `daily_approved_hours_target` belongs in `CompanyDefaults` as shared business configuration.
- Current scope is full report v1, not a phased subset.
