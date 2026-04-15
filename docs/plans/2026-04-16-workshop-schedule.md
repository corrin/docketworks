# Workshop Schedule — Backend Plan

## Purpose

Build the backend for an **operations** scheduling feature that helps office staff answer three
practical questions without opening every job individually:

1. Which active jobs are likely to miss their promised date?
2. When is each job expected to start and finish?
3. Which jobs cannot be scheduled because planning data is missing or invalid?

This is not an accounting feature. It belongs in a new `apps/operations` app.

The backend must provide two things:

- a persisted forecast of the current anticipated workshop schedule
- a stable API contract that the frontend can use directly for the Workshop Schedule screen

---

## What Success Looks Like

When this work is complete:

- the system can compute a workshop schedule forecast on a recurring basis
- the forecast is persisted as scheduling output, not written back onto `Job`
- the API exposes anticipated start/end dates for scheduled jobs
- the API clearly exposes unschedulable/problem jobs
- the response contains enough information for a calendar-first frontend
- automated backend tests cover the projection logic and endpoint contract

---

## Core Design Decision

Do **not** store scheduler output directly on `Job`.

The `Job` model should hold durable business inputs and manually maintained state, such as:

- `min_people`
- `max_people`
- actual assigned staff
- promised delivery date

Scheduler output is derived forecast data and should be persisted separately.

Create persisted schedule models in `apps/operations` for forecast output. The exact model names
may vary, but the design must include:

- one record representing a scheduler run
- one record per job projection within that run

The scheduler run record should capture things like:

- when the run occurred
- which algorithm/version produced it
- whether it completed successfully
- enough metadata to debug or compare runs later

The job projection record should capture forecast output such as:

- job reference
- anticipated start date
- anticipated end date
- anticipated staff list or equivalent projected staffing output
- remaining hours at run time
- whether the job is late
- unscheduled reason if the job could not be scheduled
- link back to the scheduler run

The API should read from the latest successful scheduler run rather than recomputing everything
from scratch on every request.

---

## Required Behaviour

Create a new endpoint:

`GET /api/operations/workshop-schedule/`

The endpoint must return three top-level collections:

- `days`
- `jobs`
- `unscheduled_jobs`

### 1. `days`

This collection supports the frontend calendar view.

Each day row must include:

- `date`
- `total_capacity_hours`
- `allocated_hours`
- `utilisation_pct`

If the implementation already has a clean way to provide projected jobs per day, the day data may
also include job references for convenience, but the main calendar should be supportable from the
job projections alone.

The endpoint must accept a `day_horizon` query parameter to limit how many day rows are returned.
Use a sensible short default appropriate for an operations planning screen.

### 2. `jobs`

This collection represents successfully projected jobs and supports the main calendar/workbench UI.

Include jobs in `approved` and `in_progress` status that were successfully projected in the latest
schedule run.

Each job must include:

- `id`
- `job_number`
- `name`
- `client_name`
- `remaining_hours`
- `delivery_date`
- `anticipated_start_date`
- `anticipated_end_date`
- `is_late`
- `min_people`
- `max_people`
- `assigned_staff`
- `anticipated_staff`

`assigned_staff` must be a list of objects with:

- `id`
- `name`

`anticipated_staff` must always be populated. The scheduler must assign specific workers to each
job in order to check `min_people`/`max_people` constraints — so it already knows which workers
it picked. The selection may be arbitrary within the available pool, but it is always specific.

The frontend will use `anticipated_start_date` and `anticipated_end_date` to render jobs as spans
on a calendar/schedule board.

### 3. `unscheduled_jobs`

Jobs must **not** be silently skipped when they cannot be scheduled. They must appear in
`unscheduled_jobs` whenever required planning input is missing, invalid, or impossible.

Each unscheduled job must include:

- `id`
- `job_number`
- `name`
- `client_name`
- `delivery_date`
- `remaining_hours`
- `reason`

`reason` must be a stable machine-readable code, not free text.

Minimum required reason codes:

- `missing_estimate_or_quote_hours`
- `min_people_exceeds_staff`
- `invalid_staffing_constraints`

Additional codes are acceptable if they are stable, documented, and useful to the frontend.

---

## Business Rules

- This feature belongs in **operations**, not accounting.
- Create a new `apps/operations` app for it.
- Remaining workshop hours must come from:
  - estimate workshop hours first
  - quote workshop hours as fallback if estimate workshop hours are missing or zero
- Used hours come from actual recorded hours.
- Office staff do **not** contribute workshop capacity.
- Most jobs can only be worked on by one person, so these defaults are intentional:
  - `min_people = 1`
  - `max_people = 1`
- Jobs needing multiple simultaneous workers are exceptions and must be configured explicitly.
- Add validation so:
  - `min_people >= 1`
  - `max_people >= 1`
  - `max_people >= min_people`
- Use a simple priority-based scheduling algorithm for v1.
- Do not introduce speculative abstractions such as a strategy-pattern interface for future
  algorithms.

---

## Scheduler Execution

This scheduler should run on a schedule rather than only on demand.

Use the existing APScheduler/shared scheduler patterns already present in the repo.

The implementation must include:

- a scheduler job that recomputes the workshop schedule forecast
- persistence of the latest successful schedule output
- fail-early error handling: if a run fails, call `persist_app_error(exc)` and leave the
  previous successful forecast intact — do not overwrite good data with a failed result

At minimum, the design should make it possible to answer:

- when was the latest forecast generated?
- did the latest run succeed?
- which algorithm/version produced it?

If the API should expose forecast freshness later, the persisted run model should make that easy.

---

## Implementation Constraints

- Follow existing repo patterns for:
  - service-layer business logic
  - DRF serializers and API views
  - persisted error handling via `persist_app_error(...)`
  - APScheduler registration and standalone job functions
- Keep business logic out of views.
- When adding `min_people` and `max_people` to `Job`, review the existing `Job` checklist in
  the model and update all affected surfaces deliberately.
- Keep scheduling logic and persistence logic separate:
  - one part computes the forecast
  - one part stores the forecast run and projections
  - one part serves the latest forecast through the API
- Use the existing timezone-consistent local date approach already used elsewhere in the repo.

### Explicitly out of scope for v1

Unless the repo already has a clean existing source of truth for them, do not design v1 around:

- public holidays
- leave
- shutdown periods
- drag-and-drop schedule editing
- complex per-staff optimisation
- sophisticated scenario comparison UI

If these are not handled, document the limitation clearly in the implementation.

---

## Automated Tests

Automated testing is required for this feature. Minimum required coverage is **targeted service
+ API**.

### Service-level tests

Cover at least:

- estimate workshop hours are used when present
- quote fallback is used when estimate workshop hours are missing or zero
- jobs with no usable estimate/quote hours appear in `unscheduled_jobs`
- office staff are excluded from capacity
- one-person default job behaviour works correctly
- multi-person jobs respect `min_people` and `max_people`
- impossible staffing situations produce the correct unscheduled reason code
- priority order affects scheduling outcomes
- jobs with no remaining hours are excluded from active projection
- projected jobs receive both `anticipated_start_date` and `anticipated_end_date`
- schedule output is persisted to run/projection records instead of writing onto `Job`

### Scheduler/persistence tests

Cover at least:

- a successful scheduler run creates a persisted run record and projected job records
- a failed scheduler run persists the error appropriately
- a failed scheduler run does not destroy the last successful forecast
- the “latest forecast” query path returns data from the latest successful run

### API-level tests

Cover at least:

- the response includes `days`, `jobs`, and `unscheduled_jobs`
- each scheduled job includes `anticipated_start_date` and `anticipated_end_date`
- scheduled jobs include `min_people`, `max_people`, and `assigned_staff`
- unscheduled jobs include stable machine-readable `reason` values
- invalid query parameters return structured `400` responses
- unexpected failures follow the repo’s normal persisted-error pattern

---

## Acceptance Criteria

The work is complete when all of the following are true:

1. A scheduler run can compute and persist a workshop schedule forecast.
2. Scheduler output is stored in operations forecast/run models, not written onto `Job`.
3. `GET /api/operations/workshop-schedule/` returns a `200` with the expected contract.
4. Scheduled jobs include `anticipated_start_date` and `anticipated_end_date`.
5. A job with estimate workshop hours schedules correctly.
6. A job with no estimate workshop hours but valid quote workshop hours still schedules correctly.
7. A job with no usable estimate or quote workshop hours appears in `unscheduled_jobs`.
8. A job with impossible staffing requirements appears in `unscheduled_jobs` with an explicit
   reason code.
9. Daily capacity rows make sense relative to known workshop staff schedules.
10. Required backend automated tests pass.

---

## Notes For The Implementer

- Write this as a junior-friendly, straightforward feature.
- Prefer clear business behaviour over clever abstractions.
- The frontend will use this as a calendar-first scheduling view, not as a conventional tabular
  report.
