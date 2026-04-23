# Sales Pipeline Report V1

## Summary

Build a full `Sales Pipeline Report` that answers one primary question: is enough approved work flowing into the shop, and if not, where is the bottleneck? The report must be reproducible historically as of `end_date`, with "today" as the default case. Keep the first implementation focused on one backend endpoint and one frontend report view, but include all 5 report sections from the draft:

- Scoreboard
- Pipeline Snapshot
- Velocity
- Conversion Funnel
- Trend

Use existing report patterns for API/view wiring. Metrics read from structured `JobEvent` records (event_type + detail/delta_after), `Job`, and CostSet summary data. No description text matching — the structured-JobEvent migration has landed, so transitions are looked up directly by `event_type` and raw field values in `delta_after`/`delta_before`.

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
  - a qualifying transition is the earliest `JobEvent` per job where `event_type="status_changed"` and `delta_after.status in ("approved", "in_progress")`, or `event_type="quote_accepted"`
  - prefer `latest_quote.summary["hours"]`; if absent, use `latest_estimate.summary["hours"]`
  - direct jobs are jobs counted here with no prior `status_changed` event into `awaiting_approval` and no prior `quote_accepted` event before the qualifying transition
  - count each job at most once per reporting period

- Pipeline Snapshot:
  - snapshot as of `end_date`, for jobs historically in `draft` or `awaiting_approval` at that cutoff
  - derive stage membership by replaying `JobEvent` rows with `event_type="status_changed"` (using `delta_after.status` / `delta_before.status`) starting from the `job_created` event's `delta_after.status` — not from current `job.status`
  - draft hours/value come from `latest_estimate.summary`
  - awaiting-approval hours/value come from `latest_quote.summary`
  - days in stage come from the most recent `status_changed` event (by timestamp) whose `delta_after.status` matches the resolved stage, on or before `end_date`

- Velocity:
  - draft to quote-sent = `created_at` to the first `status_changed` event with `delta_after.status="awaiting_approval"`
  - quote-sent to resolved = that event to the first subsequent `status_changed` with `delta_after.status="approved"` OR the first `job_rejected` / `quote_accepted` event
  - created to approved = `created_at` to first `status_changed` with `delta_after.status="approved"` or first `quote_accepted` event
  - report median, p80, and sample size only

- Conversion Funnel:
  - based on jobs created in the reporting period (`job_created` event timestamp within range)
  - compute both job counts and hours
  - quote-stage hours use quote summary; draft/direct-only hours use estimate summary
  - accepted/rejected/waiting/direct/still-draft categories must be mutually exclusive and resolved from the ordered `JobEvent` stream as of `end_date`

- Trend:
  - weekly buckets over the lookback window
  - each week includes approved hours, approved hours per working day, acceptance rate by hours, pipeline hours as of week-end, and median velocity days
  - rolling-average output is derived from the same weekly series, not recomputed from a separate query path

### Transition/event handling

Read transitions directly from structured `JobEvent` fields — no description parsing.

Event types the service cares about:

- `status_changed` — use `delta_after.status` / `delta_before.status` (raw status keys from `Job.JOB_STATUS_CHOICES`: `draft`, `awaiting_approval`, `approved`, `in_progress`, `recently_completed`, `archived`, etc.)
- `quote_accepted` — emitted when `quote_acceptance_date` is set; treat as an approval transition for velocity and scoreboard
- `job_rejected` — emitted when `rejected_flag` becomes true and status moves to `archived`
- `job_created` — carries `delta_after.status` as the initial status key and `detail.initial_status` as the display label; use the raw key

All events have `delta_after` populated with raw field keys/values for fresh writes and for historical rows backfilled by migrations 0075 and 0077. Where `delta_after` is unexpectedly missing on a pre-migration row, exclude that job from the affected metric and emit a warning (do not fall back to description parsing).

Dedupe rules:

- for each job and each metric, take the earliest qualifying event (by timestamp)
- a job that moves `approved` → `in_progress` within the same period counts as one qualifying transition (the earlier of the two)
- a job that re-enters a stage does not double-count within a single reporting period

For historical state:

- replay the `JobEvent` stream for the job up to `end_date` to resolve as-of stage membership
- starting point is the `job_created` event's `delta_after.status`; apply each `status_changed` in timestamp order
- do not use live `job.status` for historical snapshots or historical weekly trend points
- if a job has no `job_created` event and no initial `delta_after.status` to anchor replay, exclude it from the affected section and emit a warning

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
- fetch relevant `JobEvent` rows filtered by `event_type` and (where useful) `delta_after` JSON lookups
- resolve historical stage membership as of a cutoff date by replaying the per-job event stream
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
- qualifying-event resolution: `status_changed` with `delta_after.status="approved"`, `quote_accepted`, and `job_rejected` each feed the right metrics
- dedupe: job approved then moved to `in_progress` in the same period counts once
- direct-approved jobs (no prior `awaiting_approval` transition, no `quote_accepted`) appear in approved-hours totals and the direct bucket
- funnel categorization is mutually exclusive
- historical snapshot stage membership is resolved by replaying `JobEvent` up to `end_date`, not from current live status
- days-in-stage uses the most recent `status_changed` event into the stage on or before `end_date`
- velocity median, p80, and sample size are correct from known fixture data
- weekly trend points and rolling average are derived from the same underlying weekly series
- working-days divisor matches existing accounting working-day logic
- missing quote/estimate summary excludes only affected rows and emits warnings
- a job with no `job_created` event (or no usable `delta_after.status` anchor) is excluded from snapshot/velocity/funnel with a warning, not silently text-parsed
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

- Structured `JobEvent` is already merged (PRs #218, #220). All live and historical events have `event_type`, `detail`, and `delta_after`/`delta_before` populated for the fields this report needs; description text matching is not used.
- `latest_quote.summary` and `latest_estimate.summary` are acceptable v1 sources for pipeline hours/value when present.
- Historical snapshot hours/value in v1 use the latest attached quote/estimate as a practical proxy; this should be accurate for most jobs but can drift after later revisions.
- `daily_approved_hours_target` belongs in `CompanyDefaults` as shared business configuration.
- Current scope is full report v1, not a phased subset.
