# Timesheet entry slice — design

Approved 2026-08-10. Targets five specs green (16 → 21 of 40):
`timesheet/create-timesheet-entry`, `timesheet/keyboard-nav`,
`timesheet/urgent-job-defaults`, `timesheet/performance`,
`staff/staff-wage-loading`. Out of scope: `timesheet/workshop-my-time-view`
(the calendar rebuild — its own slice) and the weekly view.

## Backend: two read operations, nothing else

**`job_timesheet_entries_retrieve`** — `GET /api/job/timesheet/entries/?staff_id=&date=`,
homed in `apps/timesheet/api.py` keeping the `job_*` operation ID (the
`job_workshop_timesheets_*` precedent, decided in rewrite-status). Auth is
`SuperuserCookieJWTAuth`: it joins the management surface, which exposes other
staff members' pay data — the same documented rule as its `/api/timesheets/*`
siblings.

- The queryset already exists: `workshop_timesheet_service.list_entries`
  filters `CostLine` on `cost_set__kind="actual", kind="time", staff,
  accounting_date`, ordered by `entry_seq`. Extract the shared queryset; do
  not duplicate it.
- The envelope is new: `{cost_lines, staff, date, summary}` where
  `cost_lines` reuses the CostLine wire shape (`CostLineOut` in
  `apps/job/schemas.py` — `entry_seq` and `meta` are already on it, and the
  keyboard spec binds rows by `data-entry-seq`), `staff` carries
  the id and name parts (field naming follows v2 schema conventions — v1's
  keys are reference, not authority), and `summary` is `{total_hours,
  billable_hours, non_billable_hours, total_cost, total_revenue, entry_count,
  scheduled_hours}` with `scheduled_hours` from `Staff.get_scheduled_hours(date)`.
- Numbers cross the wire as numbers (ADR 0046).

**`accounts_staff_list`** — `GET /api/accounts/staff/` in
`apps/accounts/api.py`. Read-only staff list carrying at least `id`, name
fields, `base_wage_rate`, `wage_rate`, `date_left`, `is_office_staff`.
Superuser auth (wage data, same reasoning). The staff group's create, patch
and icon-upload operations stay with the staff slice.

**Not ported** (dead surface — zero call sites in v1's frontend):
`job_timesheet_entries_create`, `job_timesheet_jobs_retrieve`,
`job_timesheet_staff_date_retrieve`. Entry creation goes through the live
`job_jobs_cost_sets_actual_cost_lines_create`; PATCH, DELETE and approve
already exist.

## Shared grid primitives: extract, don't generalise

`CostLineGrid` is not generalised into a configurable grid — its column defs
are a module-level constant for focus-identity reasons, and the timesheet grid
inverts its core assumption (the job is a per-row editable field, not a page
constant). Instead:

- **`useAutosaveField`** moves from `features/job/costing/` to a shared home.
  It is already generic; the move is import paths only.
- **`useDraftRows`** — mechanical extraction of the phantom/draft state
  machine from `CostLineGrid`: the trailing-phantom invariant, `draftIsEmpty`,
  the deferred row-exit commit timer, the in-flight guard with disabled
  inputs, and the failed-create badge state. Parameterised by draft type and
  **commit policy**, because the two grids commit differently (below).
- Guardrail: the extraction leaves `CostLineGrid.test.tsx` untouched and
  green, and the three green grid specs (`create-estimate-entry`,
  `job-cost-entry-data`, `job-xero-quote`) are the regression net. If the
  extraction is not mechanical, stop and reassess rather than force it.

## SmartTimesheetTable

A sibling grid in `features/timesheet/`, composing the extracted primitives.
Columns in v1's order: jobPicker, company, jobName (+ urgent badge), hours,
description, labourType, rate, payItem (hidden span — test hook), billRate,
wage $, bill $, actions.

**Selector contract, verbatim (the specs bind to all of these):**

- Row: `data-automation-id="DataTable-row-{i}"` + `data-row-id` (server UUID
  or draft local id). Exactly one trailing phantom row, always last —
  `getPhantomRowIndex` counts `DataTable-row-*` and subtracts one.
- Cells: `SmartTimesheetTable-{jobPicker|company|jobName|urgentBadge|hours|
  description|labourType|rate|payItem|billRate|wage|bill|actions}-{i}`; the
  picker derives `-trigger`, `-search`, `-list`, `-option-{jobNumber}`; the
  actions cell derives `-approve`, `-delete`.
- Editable cells carry `data-grid-nav-cell="true"`, `data-grid-row`,
  `data-grid-col`; the picker trigger carries `data-entry-seq` (the backend
  `entry_seq`, null for drafts).
- The grid root carries class `.smart-timesheet-table`; the page's loading
  spinner uses `.animate-spin` and must fully disappear once loaded (the
  performance spec waits for zero `.animate-spin` elements in the document —
  no perpetual background-refetch spinner anywhere on the page).

**Job picker.** Popover + cmdk over `timesheets_jobs_retrieve`. Search
auto-focuses on open; ArrowUp/Down move the highlight; Enter and Tab commit
the highlighted option; after a pick, focus lands on the hours cell
(selected). The trigger shows `#number` plus a red `!` chip when the job is
urgent; option rows carry a red `URGENT` chip. Saved rows render the picker
disabled — a cost line's job lives on its cost set; retargeting is
delete-and-recreate.

**Billing defaults on job pick, ported precedence exactly:**

1. Non-billable job (`shop_job` or status `special`) forces
   `is_billable: false, bill_rate_multiplier: 0.0` — wins over urgent.
2. Else, if the user has not explicitly chosen a bill rate on this row,
   `bill_rate_multiplier = is_urgent ? 1.5 : 1.0` — which also resets a stale
   1.5 left by a previously picked urgent job on the same unsaved row.
3. An explicit user override is never touched.

The wage multiplier stays Ordinary in every case — urgency raises the
customer charge, not the wage. The urgent spec asserts the create payload
carries `meta.wage_rate_multiplier === 1.0`, `bill_rate_multiplier === 1.5`,
`is_billable === true`.

**Hours cell.** Accepts decimals and v1's fraction forms (`1 1/4`, `3/4`),
clamps to [0, 24], rounds to 2 dp, falls back to the previous value on
garbage. Displays humanised on commit — the specs assert the input's *value*
is `2h` and `3h 30m`, not `2` / `3.5`.

**Create policy.** A draft commits (POST to the picked job's actual cost set)
when it is ready — job picked and hours > 0 — triggered by Enter in the hours
cell or by row exit, EXCEPT that a forward Tab from hours into this row's
description defers the commit so a description can be typed first; Tab out of
the description then commits. While the POST is in flight the next phantom's
picker trigger renders disabled. On success: merge the server line, reset the
phantom, and hand focus into the new phantom's picker search (trigger focus →
popover open → search autofocus). On failure the draft stays with the
Save-failed badge.

**Saved-row autosave.** Per-field PATCH with v1's patch sets: description
alone; hours → quantity/unit_cost/unit_rev/meta; wage rate →
unit_cost/unit_rev/meta/xero_pay_item; bill rate → unit_rev/meta; labour type
→ `labour_subtype` only, echo-merging the server-repriced `unit_rev` /
`total_rev` back. The rate select (`Ord` / `1.5x` / `2.0x` / `Unpaid`) swaps
the pay item via a by-multiplier lookup over `xero_pay_items_list` —
`'Ordinary Time'` matched by name for 1.0, `|multiplier − m| < 0.01`
otherwise; the job's default pay item is restored on Ord. The pay-item spec's
Double Time assertion rides on this. The billRate trigger shows a red border
when bill multiplier ≠ wage multiplier on a billable non-shop job.

**Actions.** Approve and delete buttons on saved rows — both endpoints are
live. v1's container-level shortcuts (ArrowUp/Down row selection,
Ctrl/Cmd+Enter add, Ctrl/Cmd+Backspace delete) are deferred; no spec asserts
them.

## Entry page shell — `/timesheets/entry?date=&staffId=`

- Header: staff select with prev/next buttons; date prev/next with **weekend
  skipping** when `companyDefaults.weekend_timesheets_enabled` is false;
  Today (also lands on a weekday); formatted date; hours-vs-scheduled readout;
  Refresh; Daily Overview link. One responsive layout, not v1's two branches.
- `staffId` absent → first staff in the date-scoped list. `staffId` not in
  the list → loud error naming the staff id and the likely cause (no Xero
  payroll id) — ADR 0015, matching v1's message.
- Data loads as independent parallel TanStack queries: staff (date-scoped),
  jobs, pay items, company defaults, entries(staff, date). No waterfall —
  request parallelism is the performance spec's real intent, and every
  response must stay under the harness's 100 KB wire cap (the jobs list is
  the one to watch).
- Date and staff changes update the URL; browser back/forward changes the
  view.
- Daily Breakdown tiles (total hours, total bill, billable / non-billable
  counts) computed client-side from the loaded entries.
- Deferred with seams: the Current Jobs cards (v1 fires one `getJobSummary`
  per distinct job — an N+1 wave no spec asserts), the help dialog.

## Daily page — `/timesheets/daily?date=`

Read-only, one `getDailyTimesheetSummaryByDate` query. Header: formatted
date, native date input, prev/next (plain ±1 day — v1's daily page does not
skip weekends), Today, Refresh. Staff table with `StaffRow-row-{staffId}` /
`StaffRow-name-{staffId}`; the name click routes to the entry page with that
staff and date. The id inside the automation id must be the exact value the
entry route accepts as `staffId` — the performance spec extracts it from the
attribute. Row content (entry count, hours, completion bar, status badge,
no-entry alert) comes from the summary payload. Deferred with seams:
StaffDetailModal, MetricsModal.

## E2E port

The five specs move into `frontend/tests/e2e/` (`timesheet/`, `staff/`),
adapted to v2: the manual `#username` / `#password` logins become the v2
login fixture, generated types are camelCase, and wire shapes follow v2's
schema where it differs from v1 (v1's schema is reference, not authority).
`getPhantomRowIndex` ports into v2's helpers if not already present.

Environmental prerequisites — verify against the E2E restore DB during
implementation and record anything new in rewrite-status:

- An **"Annual Leave" job** findable by name in the picker and mapped to the
  Annual Leave pay item.
- `labour_cost_loading > 0` in company defaults.
- At least one active staff member (`date_left` null) with
  `base_wage_rate > 0`.
- The E2E user passes superuser auth (the management-surface ops require it).
- The latest weekday has at least one staff row on the daily page.

## Testing

- Backend units: both ops — envelope shape, `staff_id`/`date` params, auth
  refusals, summary math including `scheduled_hours` and `entry_count`.
- Frontend vitest, mirroring `CostLineGrid.test.tsx`'s depth: the phantom
  invariant, the create policy (Enter commit, description deferral, in-flight
  disable, focus handoff), the urgent/bill-reset precedence (port v1's 6
  urgent + 3 bill-reset cases), rate → pay-item mapping, hours
  parse/humanise.
- Done means the five specs pass under `./scripts/ops/run_e2e.sh`, with the
  three already-green grid specs as the extraction regression net.

## Deferrals recorded by this slice

StaffDetailModal, MetricsModal, Current Jobs cards, the help dialog, and the
container-level keyboard shortcuts — each behind a seam comment, listed in
rewrite-status when the slice lands.
