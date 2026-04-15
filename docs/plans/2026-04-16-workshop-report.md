# Workshop Schedule Report — Backend Plan

## Purpose

Build the backend for an **operations** screen that helps office staff answer three practical
questions without opening every job individually:

1. Which active jobs are likely to miss their promised date?
2. Which upcoming days look underused or overloaded?
3. Which jobs cannot be scheduled because required planning data is missing or invalid?

This is not an accounting report. It belongs in a new `apps/operations` app.

The backend must produce a stable API contract that the frontend can use directly for the
Workshop Schedule screen.

---

## What Success Looks Like

When this work is complete:

- office staff can load a workshop schedule report from one endpoint
- the report shows a bounded run of daily workshop capacity/allocation rows
- the report shows expected completion dates for active jobs
- the report clearly highlights jobs that are unschedulable or have planning problems
- the response includes enough job context for the frontend to display the screen without
  per-row follow-up fetches
- automated backend tests cover the scheduling logic and endpoint contract

---

## Required Behaviour

Create a new endpoint:

`GET /api/operations/reports/workshop-schedule/`

The endpoint must return three top-level collections:

- `days`
- `jobs`
- `unscheduled_jobs`

### 1. `days`

This collection supports the frontend Capacity tab.

Each day row must include:

- `date`
- `total_capacity_hours`
- `allocated_hours`
- `utilisation_pct`
- `completing_job_ids`

The endpoint must accept a `day_horizon` query parameter to limit how many day rows are
returned. Use a sensible short default appropriate for an operations planning screen.

`days` is for the display window only. Expected job completion dates may fall beyond the
returned day rows.

### 2. `jobs`

This collection supports the frontend Jobs tab.

Include jobs in `approved` and `in_progress` status.

Each job must include:

- `id`
- `job_number`
- `name`
- `client_name`
- `remaining_hours`
- `delivery_date`
- `expected_delivery_date`
- `is_late`
- `min_people`
- `max_people`
- `assigned_staff`

`assigned_staff` must be a list of objects with:

- `id`
- `name`

The frontend is expected to refresh this report after edits made through existing job/staff
assignment endpoints, so the report response must reflect current staff assignments and job
configuration accurately.

### 3. `unscheduled_jobs`

This collection supports the frontend Problems tab.

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

## Implementation Constraints

- Follow existing repo patterns for:
  - service-layer business logic
  - DRF serializers and API views
  - persisted error handling via `persist_app_error(...)`
- Keep business logic out of views.
- When adding `min_people` and `max_people` to `Job`, review the existing `Job` checklist in
  the model and update all affected surfaces deliberately.
- Keep the scheduling logic isolated enough to replace later, but do not overdesign v1.
- Use the existing timezone-consistent local date approach already used elsewhere in the repo.

### Explicitly out of scope for v1

Unless the repo already has a clean existing source of truth for them, do not design v1 around:

- public holidays
- leave
- shutdown periods
- per-staff daily allocation output
- advanced optimisation/scoring

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
- jobs with no remaining hours are excluded from active simulation
- expected completion dates are correct for simple known scenarios
- assigned staff are included in scheduled job results

### API-level tests

Cover at least:

- the response includes `days`, `jobs`, and `unscheduled_jobs`
- each scheduled job includes `min_people`, `max_people`, and `assigned_staff`
- unscheduled jobs include stable machine-readable `reason` values
- invalid query parameters return structured `400` responses
- unexpected failures follow the repo’s normal persisted-error pattern

---

## Acceptance Criteria

The work is complete when all of the following are true:

1. `GET /api/operations/reports/workshop-schedule/` returns a `200` with the expected contract.
2. A job with estimate workshop hours schedules correctly.
3. A job with no estimate workshop hours but valid quote workshop hours still schedules correctly.
4. A job with no usable estimate or quote workshop hours appears in `unscheduled_jobs`.
5. A job with impossible staffing requirements appears in `unscheduled_jobs` with an explicit
   reason code.
6. Daily capacity rows make sense relative to known workshop staff schedules.
7. Assigned staff are present in scheduled job results.
8. Required backend automated tests pass.

---

## Notes For The Implementer

- Write this as a junior-friendly, straightforward feature.
- Prefer clear business behaviour over clever abstractions.
- The frontend already expects this to support a Jobs tab, Capacity tab, and Problems tab, so
  preserve that mental model when shaping the response.
