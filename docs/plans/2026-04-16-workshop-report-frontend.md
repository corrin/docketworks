# Workshop Schedule Report — Frontend Plan

## Purpose

Build a Workshop Schedule screen that lets office staff:

- see which jobs are likely to finish late
- see upcoming workshop capacity and utilisation
- see which jobs cannot be scheduled because planning data is missing or invalid
- take simple corrective actions without leaving the page where practical

This screen is the frontend consumer of the backend operations report described in
`docs/plans/2026-04-16-workshop-report.md`.

---

## What Success Looks Like

When this work is complete:

- office staff can open a single Workshop Schedule screen from the reports/navigation area
- the screen has three clear views of the same report data:
  - Jobs
  - Capacity
  - Problems
- the screen highlights late jobs and scheduling problems clearly
- the screen supports quick operational edits where existing backend endpoints already allow them
- frontend types come from generated API schema, not hand-written guesses
- automated frontend checks pass

---

## Backend Contract This Screen Depends On

Before frontend work starts, the backend must provide:

`GET /api/operations/reports/workshop-schedule/`

with top-level collections:

- `days`
- `jobs`
- `unscheduled_jobs`

### Required `days` fields

- `date`
- `total_capacity_hours`
- `allocated_hours`
- `utilisation_pct`
- `completing_job_ids`

### Required `jobs` fields

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

`assigned_staff` must contain:

- `id`
- `name`

### Required `unscheduled_jobs` fields

- `id`
- `job_number`
- `name`
- `client_name`
- `delivery_date`
- `remaining_hours`
- `reason`

The frontend expects stable machine-readable `reason` codes from the backend.

---

## Required Screen Behaviour

Create a new route:

- `/reports/workshop-schedule`

Add a navigation entry alongside the existing report links.

Build one screen with three tabs using the backend report response.

### 1. Jobs tab

This tab helps staff see what needs attention first.

Required behaviour:

- late jobs sort to the top
- jobs are visually distinguishable by status
- job rows show:
  - job number
  - job name
  - client
  - remaining hours
  - promised date
  - expected completion date
  - status
  - min people
  - max people
  - assigned staff
  - open-job link

Required status handling:

- `is_late=true` should be treated as late
- jobs with no promised date should be visually distinct from on-track jobs

### Inline edits allowed on this screen

Use existing backend job endpoints. Do not invent new endpoints in this frontend task.

This screen should support:

- editing `delivery_date`
- editing `min_people`
- editing `max_people`
- assigning staff
- unassigning staff

After each successful edit, reload the schedule report so the display reflects recalculated
scheduling results.

### 2. Capacity tab

This tab helps staff see upcoming aggregate workshop load.

Required behaviour:

- render one row per day from `days`
- show capacity, allocated hours, and utilisation
- clearly distinguish days with no capacity
- show which jobs complete on each day using job numbers rather than UUIDs

This is aggregate capacity only. Per-staff utilisation is out of scope for v1.

### 3. Problems tab

This tab helps staff identify jobs that require manual correction before they can be scheduled.

Required behaviour:

- show all items from `unscheduled_jobs`
- show the problem count clearly
- translate machine-readable backend reason codes into readable labels
- if there are no problem jobs, show an explicit empty state

Minimum reason-label mappings:

- `missing_estimate_or_quote_hours` → readable “no hours estimate” style text
- `min_people_exceeds_staff` → readable “not enough staff” style text
- `invalid_staffing_constraints` → readable validation/problem text

Unknown codes may be shown as raw strings rather than hidden.

---

## Implementation Constraints

- Follow the same frontend architecture style as the existing report screens.
- Use generated API types/schema, not manually authored request/response types.
- Keep this as a single report screen with a thin service layer; do not add a separate store
  unless there is a clear existing pattern requiring it.
- Reuse existing job update and staff assignment APIs for edits.
- Do not move estimate editing into this screen. Opening the job detail screen remains the
  correct path for deeper costing/estimate work.

---

## Automated Checks

The frontend plan must include automated validation, even if it is lightweight.

At minimum, require:

- schema update and API client generation
- type checking
- linting if the surrounding report workflow already expects it

If the repo already has a practical test pattern for report views, follow it. If not, do not
invent a large new frontend test framework just for this feature.

---

## Acceptance Criteria

The frontend work is complete when all of the following are true:

1. `/reports/workshop-schedule` is reachable from the app navigation.
2. The screen loads without console errors using the generated API client/types.
3. The Jobs tab shows late jobs first and displays the required job fields.
4. Editing promised date or people constraints triggers the existing backend update flow and the
   report reloads afterward.
5. Staff can be assigned and unassigned from the Jobs tab using existing assignment endpoints,
   and the report reloads afterward.
6. The Capacity tab shows daily rows, utilisation, and completing jobs in a readable way.
7. The Problems tab shows unscheduled jobs with readable reason labels and an empty state when
   none exist.
8. Required frontend automated checks pass.

---

## Notes For The Implementer

- This screen is an operations work surface, not just a passive report.
- The goal is to help office staff make quick planning decisions.
- Keep the UI straightforward and familiar by following the existing report screen patterns in
  the repo.
