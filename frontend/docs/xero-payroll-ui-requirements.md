# Xero Payroll UI Requirements

**Status: blocked-by:payroll-employees.** The backend API below exists and is in
the generated client; the weekly-timesheets page that consumes it is not built
(routes today: `timesheets/entry`, `timesheets/daily` only). This document is
the UI contract for that slice. Spec-first rule applies: the slice ships with
its E2E spec.

## Overview

The office manager needs UI to:

1. Create Draft pay runs for weekly periods
2. Post staff timesheet weeks to the pay run in Xero
3. View posting results and handle errors

**Weekly process:**

1. **Monday–Friday:** daily timesheets entered as normal (no change to the
   existing entry UI).
2. **End of week:** on the weekly timesheets page, create the week's pay run if
   it does not exist, post hours to Xero for staff, review results.
3. **In Xero:** the office manager reviews, approves, and posts the pay run,
   which locks it.
4. Once Posted in Xero, the week cannot be modified from DocketWorks.

## Backend API (already live — use the generated hooks, never hand-rolled calls)

All four operations are on the timesheet router (`apps/timesheet/api.py`),
require office-manager auth (`manage_auth`), and are exposed through the
generated TanStack Query layer (`src/api/generated/@tanstack/react-query.gen.ts`):

| Operation | Endpoint | Generated hook |
|---|---|---|
| List pay runs (local mirror) | `GET /api/timesheets/payroll/pay-runs/` | `timesheetsPayrollPayRunsRetrieveOptions` |
| Create pay run for a week | `POST /api/timesheets/payroll/pay-runs/create` | `timesheetsPayrollPayRunsCreateCreateMutation` |
| Refresh mirror from Xero | `POST /api/timesheets/payroll/pay-runs/refresh` | `timesheetsPayrollPayRunsRefreshCreateMutation` |
| Post staff weeks to Xero | `POST /api/timesheets/payroll/post-staff-week/` | `timesheetsPayrollPostStaffWeekCreateMutation` |

Wire shapes (`apps/timesheet/schemas.py`):

- **List** returns `{ pay_runs: [...], next_postable_week_start_date,
  next_postable_week_end_date }`; each pay run carries `id`, `xero_id`,
  `period_start_date`, `period_end_date`, `payment_date`, `pay_run_status`, and
  `xero_url` (deep link into Xero — render it as "Open in Xero").
  `next_postable_*` is the server's ruling on which week can be posted next; the
  UI derives "can I create/post here?" from it rather than re-implementing the
  calendar rule.
- **Create** takes `{ week_start_date }` (a Monday) and answers 201 with the new
  run, or 400 with the validation message (not-a-Monday, existing draft run).
- **Refresh** answers `{ synced, fetched, created, updated }` — surface a short
  "Synced N pay runs" confirmation.
- **Post** takes `{ staff_ids: [uuid, …], week_start_date }` — posting is a
  **batch, asynchronous** operation. The response is `{ task_id, stream_url }`;
  the actual posting happens while the client consumes the SSE stream at
  `stream_url` (`payroll/post-staff-week/stream/{task_id}/` — a plain SSE view,
  not a ninja operation, so it is not in the generated client; open it with
  `EventSource`). Progress and per-staff results arrive as stream events.
  A single-staff "Post" button sends a one-element `staff_ids`.

The weekly data itself comes from `GET /api/timesheets/weekly/`
(`timesheets_weekly_retrieve`, optional `start_date`, defaults to the current
week) — per-staff daily hours, leave split (sick/annual/bereavement), overtime,
and costs.

## Page: Weekly Timesheets

### 1. Pay-run management section (top of page)

Display the selected week, its payment date, and pay-run status:

- **Draft**: "Pay run ready for posting"
- **Posted** (locked): "Pay run locked (already paid)"
- **Not created**: "Pay run not created yet"

(No emoji/icon-only status — words, per repo convention.)

**"Create Pay Run for This Week"** button — visible only when no pay run exists
for the selected week and the server's `next_postable_week_start_date` allows
it. On 400, show the backend message; the known cases are a non-Monday date and
"only one draft pay run" (tell the user to post or delete the existing draft in
Xero first, then Refresh).

**"Refresh from Xero"** button — runs the mirror sync; needed after the office
manager posts or deletes a run inside Xero.

### 2. Staff posting section

One card/row per staff member with hours this week, showing the hour breakdown
from the weekly payload (work, leave split, overtime). Post button states:

- Disabled with tooltip "Create pay run first" when no draft run exists.
- Disabled with tooltip "This week is locked" when the run is Posted.
- While the SSE stream is open: progress indicator ("Posting 3 of 10 staff…"
  for bulk, spinner for single), buttons disabled to prevent double-posting.
- On completion: per-staff success/error from the stream events; failed staff
  keep an actionable error, successful ones show the posted breakdown.

**"Post All Staff to Xero"** sends every listed staff id in one request and
drives the same progress UI from the one stream.

**Open item for the slice:** the weekly payload does not yet carry per-staff
"posted to Xero / last posted at" state, so posted-status persistence across a
page reload needs a backend addition (or it stays session-local and the page
says so). Decide in the slice; do not invent a client-side cache silently.

### 3. Re-posting

If hours are edited after an initial post (but before the run is Posted in
Xero), posting again is legal — the backend replaces the previously posted
lines. Label the button "Re-post to Xero" where the session knows a prior post
happened.

## Error handling

Errors are transparent after authentication (ADR 0038) — show the backend
message, augmented with the action that fixes it:

| Backend condition | UI guidance to append |
|---|---|
| week_start_date not a Monday | Client-side week picker should only offer Mondays; if it slips through, show the message as-is |
| No pay run for the week | Point at the Create button above |
| Pay run already Posted | "This week's payroll is finalized in Xero. Contact payroll if corrections are needed." |
| Staff not linked to Xero (no xero_user_id) | "Ask an administrator to link this staff member to Xero." |
| Only one draft pay run allowed | "Post or delete the other draft in Xero, then Refresh." |
| Xero connection/auth failure | Show the error; the Xero connection page is the fix |

## Permissions

The endpoints are superuser/office-manager only (`manage_auth`); the page is
management UI and is not shown to workshop self-service users.

## Testing checklist for the slice's E2E spec

- Create-pay-run button appears only when no run exists for the week
- Post buttons disabled without a run, and when the run is Posted
- Posting drives the SSE progress UI and ends with per-staff results
- Re-posting after an hours edit succeeds
- Week picker navigation updates run status and staff list together
- Error cases above render their messages
- Xero fidelity: real demo-company pay-run objects, cleaned per
  [`e2e-testing-strategy.md`](e2e-testing-strategy.md)
