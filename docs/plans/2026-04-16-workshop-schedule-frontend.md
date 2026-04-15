# Workshop Schedule — Frontend Plan

## Purpose

Build a **calendar-first** Workshop Schedule screen that helps office staff make quick operational
decisions:

- see when active jobs are expected to start and finish
- see which jobs are likely to finish late
- see upcoming workshop capacity and overloaded/underused days
- see which jobs cannot be scheduled because planning data is missing or invalid
- open a job directly from the schedule
- make simple corrective edits without leaving the screen where existing APIs already allow it

This screen is the frontend consumer of the backend described in
`docs/plans/2026-04-16-workshop-schedule.md`.

This is not a classic “report page.” It should feel like a time-based sibling to Kanban: an
operations work surface built around time instead of status columns.

---

## What Success Looks Like

When this work is complete:

- staff can open the Workshop Schedule screen from the main navigation
- the main visual is a calendar/schedule board, not a table-first report
- scheduled jobs appear as cards/bars spanning anticipated start to anticipated end
- clicking a scheduled job takes the user to that job
- colour makes overload, lateness, and problem states obvious
- the screen still includes a clear place to see unscheduled/problem jobs
- API types come from generated schema, not hand-written interfaces
- required frontend checks pass

---

## Existing Frontend Patterns To Follow

Do not invent a new architecture for this screen. Follow the existing frontend patterns already
in the repo, while adapting them to a calendar-first experience.

Use these as reference points:

- `frontend/src/views/JobAgingReportView.vue` for page loading/error/action shell patterns
- `frontend/src/router/index.ts` for route registration
- `frontend/src/components/AppNavbar.vue` for desktop and mobile navigation links
- `frontend/src/services/job.service.ts` for partial job header updates
- generated API aliases already present in `frontend/src/api/generated/api.ts` for:
  - `accounts_staff_list`
  - `job_job_assignment_create`
  - `job_job_assignment_destroy`

For the new service, use `import { api } from '@/api/client'` and `z.infer<typeof schemas.X>`
for all types. Do not copy the axios import or hand-written interface pattern from existing
report services — those predate the generated client and do not follow current frontend rules.

Keep this feature as one screen plus a thin service. Do not add a store unless there is a clear,
existing pattern that requires it.

---

## Backend Contract This Screen Depends On

Before frontend work starts, the backend must provide:

`GET /api/operations/workshop-schedule/`

with top-level collections:

- `days`
- `jobs`
- `unscheduled_jobs`

### Required `days` fields

- `date`
- `total_capacity_hours`
- `allocated_hours`
- `utilisation_pct`

### Required `jobs` fields

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

`assigned_staff` and `anticipated_staff` must contain:

- `id`
- `name`

`anticipated_staff` is always populated — the scheduler assigns specific workers to check
`min_people`/`max_people` constraints, so it always knows which staff it picked.

### Required `unscheduled_jobs` fields

- `id`
- `job_number`
- `name`
- `client_name`
- `delivery_date`
- `remaining_hours`
- `reason`

The frontend expects stable machine-readable `reason` codes from the backend.

If the backend contract changes, regenerate schema/types before doing frontend work.

---

## Required Screen Behaviour

### Route and navigation

Create a new route:

- `/schedule`

Register it in `frontend/src/router/index.ts` using the same lazy-loaded route style as the
existing views.

Add a "Schedule" link in `frontend/src/components/AppNavbar.vue` alongside the existing Kanban
Board link, in both:

- the desktop navigation
- the mobile menu

Follow the exact structure already used there rather than inventing a new nav pattern.

### Overall screen

Build one screen with three main areas:

- schedule calendar
- capacity summary/indicators
- problem jobs area

Use the same overall page discipline as the report views:

- App layout wrapper
- page title and actions
- loading state
- error state
- main content area

But the **primary content must be the calendar/schedule board**.

### Main schedule calendar

This is the primary UI and should answer:

- when is each job expected to start?
- when is each job expected to finish?
- where are jobs overlapping in time?
- which jobs are late?

Required behaviour:

- render a bounded calendar/time view using the returned `days`
- render each scheduled job as a card/bar spanning:
  - `anticipated_start_date`
  - `anticipated_end_date`
- cards must be clickable and navigate to `/jobs/:id`
- jobs that are late must be visually distinct
- days with no capacity must be visually distinct
- overloaded/high-utilisation days must be visually distinct
- low-utilisation days should also be distinguishable

For v1, keep layout simple:

- day columns
- jobs stacked within the day grid
- no drag-and-drop scheduling
- no complex resize interactions

This should be a readable schedule board, not a full scheduling application.

### Secondary job details/editing

The calendar is primary, but the screen must still allow lightweight operational corrections.

Use existing backend endpoints only. Do not invent new endpoints for this feature.

This screen should support:

- editing `delivery_date`
- editing `min_people`
- editing `max_people`
- assigning staff
- unassigning staff

These edits do not need to happen directly on the calendar card if that would make the UI messy.
It is acceptable to use:

- a details panel
- a selected-job side panel
- a supporting list below the calendar

Use the existing partial job update flow in `frontend/src/services/job.service.ts` for job header
edits.

Use the generated assignment endpoints for assign/unassign actions.

After each successful edit, reload the workshop schedule so the screen reflects recalculated
scheduling results.

### Staff list source

The schedule response gives currently assigned and anticipated staff per job, but the screen still
needs a list of available workshop staff for adding assignments.

Fetch the full staff list once using the generated `accounts_staff_list` endpoint and filter out
office staff client-side.

Do not fetch staff separately for every job.

### Capacity indicators

The screen must communicate day-level capacity clearly, even if the day data is not the primary
visual element.

Required behaviour:

- show per-day utilisation using colour and/or compact numeric indicators
- make high-utilisation days visually obvious
- make no-capacity days visually obvious
- keep capacity comprehension fast at a glance

### Problem jobs area

The screen must include a clear place to see unscheduled/problem jobs.

This can be:

- a side panel
- a bottom panel
- a dedicated tab/section

But it must remain visible and easy to access from the same screen.

Required behaviour:

- show all entries from `unscheduled_jobs`
- show the problem count clearly
- translate backend `reason` codes into readable labels
- show an explicit empty state when there are no problems

Minimum reason-label mappings:

- `missing_estimate_or_quote_hours` → readable “no hours estimate” style text
- `min_people_exceeds_staff` → readable “not enough staff” style text
- `invalid_staffing_constraints` → readable validation/problem text

Unknown reason codes may be shown raw rather than hidden.

---

## Implementation Constraints

- Use generated API types/schema, not hand-written request or response interfaces.
- Keep this feature as a single screen with a thin service.
- Reuse existing job update and staff assignment flows.
- Do not move estimate editing into this screen. Opening the job detail screen remains the
  correct path for deeper estimate/costing changes.
- Keep the UI familiar and practical. This should feel like an operations screen, not an abstract
  design exercise.

---

## Automated Checks

Automated validation is required for this frontend work.

Minimum required checks:

- regenerate schema and API client
- type check
- lint if that is part of the normal frontend workflow for touched files

Concretely, require:

- `npm run update-schema`
- `npm run gen:api`
- `npm run type-check`

If the normal workflow in this repo also expects lint to pass for touched files, require that as
well rather than treating it as optional.

Do not invent a large new frontend test suite just for this screen unless the repo already has a
lightweight, established pattern that fits naturally.

---

## Acceptance Criteria

The frontend work is complete when all of the following are true:

1. `/schedule` is reachable from the router and from the main navigation in both desktop and
   mobile layouts.
2. The screen loads without console errors using generated API types/client code.
3. The main UI is calendar-first, with scheduled jobs rendered as spans/cards from
   `anticipated_start_date` to `anticipated_end_date`.
4. Clicking a scheduled job opens that job.
5. Late jobs, overloaded days, and no-capacity days are visually obvious.
6. There is a clear on-screen area for unscheduled/problem jobs with readable reason labels and
   an explicit empty state when none exist.
7. Editing promised date or people constraints uses the existing job update flow and reloads the
   schedule afterward.
8. Staff can be assigned and unassigned using existing assignment endpoints, and the schedule
   reloads afterward.
9. Required frontend checks pass.

---

## Notes For The Implementer

- This is an operations work surface, not a passive report.
- Optimize for fast comprehension first.
- If you are unsure how to structure the page, keep the interaction model simple and avoid
  turning v1 into a drag-and-drop planning tool.
