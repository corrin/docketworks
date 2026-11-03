# One way to put time onto a job

## Context
The owner typed "4h" into an hours box in the Timesheets menu and it was refused. A review on 2026-11-02
found why: the menu has **three separate time-entry implementations**:

| Surface | Hours input | Wire format / endpoint |
|---|---|---|
| Office entry grid (`SmartTimesheetTable.tsx`) | free text → `parseHoursInput` (`hours.ts:17`): "4h", "1 1/4", "3h 30m" all work | `TimesheetCreateBody` → `/job/jobs/{id}/cost_sets/actual/cost_lines/` → `job_service._create_timesheet_entry` translates it → `create_entry` |
| My-time drawer (`WorkshopTimesheetEntryDrawer.tsx:415`) | `type=number` + `Number()`: "4h" reads as blank, Save stays disabled | `WorkshopTimesheetEntryRequest` → `/job/workshop/timesheets/` → `create_entry` |
| Fill-day sheet (`FillDaySheet.tsx:204`) | `type=number` + `Number()`: same, plus a quarter-hour rule enforced only by the server | `/timesheets/my-day/submit/` → `submit_day` → `create_entry` per row |

The backend already has one writer (`workshop_timesheet_service.create_entry/update_entry/delete_entry`).
The duplication is in the frontend and in the two API routes into that writer:
- **Hours input and parsing:** three of each.
- **Rate options:** three versions: `RATE_OPTIONS` (`SmartTimesheetTable.tsx:123`), `rateOptionsFor` (`myTime.ts:189`), and a 1.5 checkbox (`FillDaySheet.tsx:231`).
- **"Bills its time" rule:** twice in the frontend (`timesheetDraft.ts:65`, `myTime.ts:244`) and once on the server.
- **Urgent 1.5 bill rate:** applied by both the client (`applyJobPick`) and the server.
- **Overtime question:** two separate implementations (drawer :265, fill sheet :77). The grid has none.
- **Draft row:** three shapes (`TimesheetDraft`, eight `useState`s in the drawer, `FillSheetRow`).
- **Save hooks:** two, with different cache keys (`useTimesheetEntries`, `useWorkshopEntryWrites`).
- **Delete endpoints:** two.
- **General work:** two hooks (`useClocking.fillWithGeneralWork`, `useSweep`).

Already shared, and kept as it is: `JobPicker` + `timesheetJobSearchOptions`, `OvertimeAskDialog`, `BreakSheet`,
`formatHoursDisplay`, and the backend writer. Placing an entry that has no times is also one rule:
`default_entry_start` (`workshop_timesheet_service.py:429`) used through `next_entry_start` by both the
writer (`_placed`) and the drawer's preview (`timesheets_my_day_placement`).

## Approach (recommended)
Keep the three screens. They serve different people at different moments: the office keying a week, a
worker fixing one entry on a phone, and a worker filling the day after clock-out. Make each screen a thin
layout over **one set of entry parts and one write path**.

1. **One hours field.** *(Done 2026-11-02.)* Add `HoursInput` in `features/timesheet/`. It is a text input (`inputMode="decimal"`) that parses
   with `parseHoursInput` and shows `formatHoursDisplay`. It replaces the grid's cell input, the drawer's
   field and the fill sheet's field. `parseHoursInput` gains a blank → `null` mode for the drawer and fill
   sheet, which need "not sized yet" rather than a fallback. Delete the now-false comment at `myTime.ts:5-7`.
2. **One hours rule.** It lives in the writer, `create_entry`/`update_entry`, and is not split across `lay_out_rows` and
   the client clamp (see decision 2).
3. **One write API.** *(Done 2026-11-02.)* The grid moves to `/job/workshop/timesheets/`:
   - `WorkshopTimesheetEntryRequest` gains `labour_subtype` and `bill_rate_multiplier`, which only the grid sends.
   - Delete `job_service._create_timesheet_entry` / `_update_timesheet_entry`, the `created_from_timesheet` routing in
     `create_cost_line` / `update_cost_line` / `delete_cost_line`, and `TimesheetCreateBody`. Actual time
     on the cost-line endpoints is then refused outright, which closes the unmarked-line hole as well.
   - Regenerate the client.
4. **One write path, one refresh.** The grid's hook (`useTimesheetEntries`) and the drawer's
   (`useWorkshopEntryWrites`) call the same three entry endpoints, and every write of a person's time
   (grid, drawer, clocking, breaks, send the day) refreshes the same views through one
   `invalidateEntryViews`. The two hooks stay two: the grid is optimistic because its focus moves on, the
   drawer is a modal that waits. The entry endpoints answer with an entry, not a priced line, so a new
   grid row is read back from the day (one extra read per office create; not a hot path). *(Done
   2026-11-02. Correction: this does NOT close the 412-after-grid-edit gap in `job/invalidateJobViews.ts:18`;
   that stays the backlog's server-side `_set_job_etag` item.)*
5. **One copy of each rule:** *(Done 2026-11-03. Rate constants live once in `time_entry_rates`: `DEFAULT_MULTIPLIER`, `OVERTIME_MULTIPLIER`, `ZERO_MULTIPLIER`.)*
   - Rate options: `rateOptionsFor`. The grid adds "unpaid" through a parameter.
   - Bills its time: one `billsItsTime`.
   - Urgent 1.5: server only. The grid sends `bill_rate_multiplier` only when the user changes it.
   - Blank-to-null: `orNull`.
   - The overtime question: one `askOvertimeThenSend(rows, jobId)` used by the grid, the drawer and the fill sheet. It always sends `job_id`; today the fill sheet omits it.
6. **General work:** one hook over the two endpoints, or one endpoint if the sweep can call the my-day one. *(Done 2026-11-03, on the backend: the sweep fills through `fill_with_general_work`, and `general_work_job_id` is the one validated lookup. The two frontend hooks stay two because they are two operations: a worker fills his own day, while the office's sweep fills, approves and sends.)*

Perf posture: this makes no kanban or hot-path change. The grid's optimistic save is kept, and the drawer and fill sheet gain it.

## Open issues (each is the owner's decision unless marked)
1. [x] **Scope** (owner, 2026-11-02): three screens over shared parts.
2. [x] **Hours rule** (owner, 2026-11-02): any 2dp value up to 24h, enforced in the writer. `lay_out_rows` drops its quarter-hour refusal.
3. [x] **Overtime question** (owner, 2026-11-02): it is the same whoever enters the time, so the office grid asks it too, through the same `askOvertimeThenSend`.
   - Hours add up whoever enters them: the worker's 4h plus the office's 3h is 7h.
   - Time of day is only a reminder for the worker. It means nothing for pay or overtime.
4. [x] **Leave** (owner, 2026-11-02): fold `leave_service._create_days` / `_delete_days` into `create_entry` / `delete_entry`. *(Coded: ceec5628. Leave lines carry `managed_by=leave` and are approved when made; the cost-line route's time repricing is deleted.)*
   - This removes the general writer's last time-line caller, `_reprice_timesheet_line`.
   - Leave is never overtime: `overtime_part` already returns 0 for leave jobs.
5. [x] **Repair commands** (owner, 2026-11-02): they stay, but `create_overtime_entries`, `reclassify_overtime_entries` and `reassign_time_entries` write through `create_entry` / `update_entry`.
   - These are reusable tools: two line a week up with what Xero payroll paid, and one moves entries between people.
   - `_repair_shared.build_repair_time_line` and each command's own pricing are deleted.
   - This closes the backlog item at `docs/rewrite-status.md:171` (1.5x and 2x lines priced at the base wage). The tests that pin that bug (`test_repair_commands.py:234`, `:367`) flip to assert the correct price.
   - The rate constants become one definition. Today they are defined at `workshop_timesheet_service.py:823`, `attendance.py:986` and `day_submission.py:36`.
6. [x] **Estimate and quote grids** (owner, 2026-11-02): use `HoursInput` there too, so there is one hours field app-wide (`CostLineGrid.tsx:356`).
7. [x] *(mine)* The branch `fix/timesheet-writes-one-writer` has its plan fully ticked. This work needs its own branch and PR: the owner created `fix/one-time-entry`, PR #230, stacked on #229.
8. [ ] **`main`'s CI is red** (2026-11-02, run on 07:05Z): `npm audit --audit-level=high` fails on `follow-redirects` 1.16.1. This branch carries the lockfile-only fix (`aa91b128`); `main` needs it on its own, ahead of this stack. Opened 2026-11-03 as PR #231: the same commit, pushed as its own branch off `main`, so no branch switch was needed. It closes when #231 merges.
9. [x] *(2026-11-03: the full vitest run passed 795/795 with no flake; nothing to fix unless it returns)* **The full frontend unit run flakes locally**: 1 to 3 different `findBy` timeouts per run (`JobQuoteTab`, `JobActualTab`, `JobMovementReportPage`; each passes alone, 3 of 3). The reports page shares no code with this change. CI's unit runs were green on #229. Find the cause before this PR is ready, not by raising a timeout.

10. [ ] **Repair commands price at today's rates** (owner's decision, found 2026-11-03). They now write through the entry writer, which prices every line at the worker's current wage and the job's current charge-out rate. A repair of an old week used to keep each line's own historical figures, so if a wage changed since that week, the repair prices it at the new wage. Separately, `create_overtime_entries` now refuses an ordinary row on a day already past the usual 8h, because the writer would put it at 1.5x and the week would disagree with Xero. Recommendation: accept both. Wage changes are rare at six staff, and the refusal says which row to move. The alternative is a "this rate was chosen" flag on `create_entry` plus historical prices, which is more code for a rare repair.

## Tests
- **E2E (the done gate):**
  - Each hours field reads the typed form: the grid books `4h` (`create-timesheet-entry`), the drawer `2h` (`workshop-my-time-view`), the fill sheet `2h` (`workshop-fill-day`), the estimate grid `2h` and shows `2` after a reload (`create-estimate-entry`). The parser's other forms (`1 1/4`, `3h 30m`) are unit-tested in `features/shared/hours.test.ts`.
  - In the office grid, an ordinary-rate entry that takes the day past its usual hours asks the overtime question, as the drawer does.
  - Leave booked on a day with General work rebuilds the General work around it.
  - The existing `tests/e2e/timesheet/*` specs stay green, each on its own `BOOKING_WEEKS` week.
- **Unit:**
  - `hours.test.ts` gains the blank → `null` mode.
  - The backend test that the cost-line endpoints now refuse every actual time line (it replaces the routing tests).
  - The workshop endpoint accepts `labour_subtype`/`bill_rate_multiplier`, and refuses a colleague's line for a non-office user.
- **Gates:** `npm run type-check`, `uv run pytest apps/timesheet apps/job`, then the full E2E with `--max-failures=0`.

## Cruft against the owner's six rules (approved 2026-11-03)

### Context
The owner set out how timesheets work (2026-11-03):
1. Staff are supposed to clock in and out. If they don't, the defaults are used.
2. Staff enter what they did. General work may fill the rest of the day.
3. The office can always do any of this for them.
4. The audit log shows who did what, from where and when (for example, a remote edit of the clock times).
5. Entry start and stop times are only a reminder. The app may move them to fit the day.
6. Staff forget breaks. The app knows them and takes them out of the time billed. Pay runs from clock-in to clock-out, less unpaid breaks.

Three read-only searches and a read of the writer found code that does more than these rules ask. Everything below is to delete or to merge; none of it is a new feature.
**Testing happens after the coding.** Each step is coded, then the PR runs unit tests, type-check and one full E2E at the end.

### Before anything: commit what is coded *(done: d0a5e74e)*
These are on the branch, uncommitted:
- `orNull` in the drawer and fill sheet
- `billsItsTime` used in `applyJobPick`
- the urgent bill rate set by the server only
- the hours rule in the writer (`_refuse_bad_hours`, any 2dp > 0 and ≤ 24)
- `lay_out_rows`'s quarter-hour refusal deleted
- the test flipped (`test_w3_…`)

### Rule 1: no clock record means the standard day, everywhere *(coded: ceec5628. Correction: the `sent_only_when_clocked_out` constraint stays, because `settle_day` writes the default clock-out before a day is sent.)*
A day nobody clocked has no `AttendanceDay` row, and several paths refuse to run without one. A separate "use standard hours" path then writes a row so they will.
The fix is one rule: the day's span is its clock times where they exist, and the standard day otherwise (`attendance.standard_day`).
- Read the span through one function, used by:
  - `fill_figures` (`attendance.py:285`)
  - `unallocated_windows` (`:344`; a missing clock-out on a past day takes the standard finish)
  - `fill_with_general_work` (`workshop_timesheet_service.py:775`)
  - `_sweep` (`approval.py:524-552`)
  - `submit_day` (`day_submission.py:112`)
  - adding a break (`attendance.py:1010`)
  - `clock_out` with no clock-in (`attendance.py:691`; the clock-in takes the standard start)
- Delete:
  - `use_standard_hours` and its endpoint (`api.py:599`)
  - `recordStandardHours` (`useWorkshopDay.ts:268`)
  - the `standard_hours_used` event
  - the sweep's row-writing branch (`approval.py:541-552`)
  - the skip reasons `no_clock_times` / `still_clocked_in` for past days (`approval.py:335-540`, `useSweep.ts`)
  - the "No clock out. Use 15:00?" offer (`DayCard.tsx:195`, `missed_clock_out_finish`)
  - the pending banner's "still clocked in" half (`attendance.py:610`, `DayCard.tsx:164`)
  - the `sent_only_when_clocked_out` constraint (`models.py:317`; a schema migration)
  - the "Clock out to see what is left" copy
- Keep:
  - "Not clocked in" as the day's status word
  - the pending banner's "not sent" half

### Rule 2: one General work *(coded)*
- One fill. `_sweep` calls `fill_with_general_work` and computes nothing of its own.
- One job lookup. `refill_general_work` and `_with_general_work` use the sweep's validated `_general_work_job_id()`.
- Frontend: one hook for the my-day fill and the sweep (step 6 of the PR #230 plan).

### Rule 3: the office does any of it for them *(coded. Correction: both approve endpoints stay. Each calls the one `approval.approve_line`; per-day is a person's day in one request and one transaction, so it is not a copy.)*
- **Send the day.** `submit_day` gains an owner and actor, as `create_entry` has. The endpoint takes `staff_id`, and `useSubmitDay` takes `ownerId`. Today only the worker can send their own fill sheet.
- **Approve.** Approve has two endpoints doing one thing: per day (`api.py:855`) and per line (`job/api.py:986`). Keep one, the per-line one, since the per-day one is a loop over it.
- **Leave.** Leave writes through `create_entry` / `delete_entry`: step 4 of the PR #230 plan, unchanged. This also fixes the bug the search found: leave never rebuilt General work.

### Rule 4: the audit log is the record of who did what *(coded: ceec5628; pay is hidden from office staff in the history)*
In plain terms: the screens show badges such as "Entered late", "Sent late", "Suspicious remote entry", "Did not clock in" and "Clocked in away from the workshop". Each badge is a second copy of something the audit log already records, so one fact is kept in two places. The owner wants the audit log to be the record (2026-11-03: "Audit logs are good"). So the badges and their stored columns go, and office staff read the log instead.
`TimesheetEvent` already records the actor, the worker, the time, before and after, and `trusted` (at the workshop or not). These copies of the same facts go:
- `CostLine.remote_entry`: a column, so a migration.
- `AttendanceDay.clock_in_how` / `clock_out_how` (`ClockHow`), with `_by_hand`, `_tapped` and `clock_cautions`.
- The derived marks `entered_late` and `sent_late`.
- `LeaveRequest.created_by`, which nothing reads.

Who sees the log: today only superusers, on the entry page (`TimesheetHistoryDialog`). Office staff move to the same `office_auth` as Approve time, and the dialog opens from Approve time's person row.
Also fix the side finding: system writes (General work refill, deletes) record `trusted` the same way `create_entry` does.

### Rule 5: entry times are a reminder *(coded: `_fit_times`)*
- **`_validate_time_consistency`** (`workshop_timesheet_service.py:249`) refuses hours longer than the start-to-finish span. Instead, the writer keeps the hours and the start and moves the finish (`attendance.finish_in_the_day`). A backwards finish is dropped and re-placed the same way.
- **`_refuse_all_inside_a_break`** (`:820`): delete it. An entry typed inside a break starts after the break (`attendance.start_after_breaks`, already used by `lay_out_rows`).
- **The drawer's "already booked for that time" warning** (`overlapsBooked`, `WorkshopTimesheetEntryDrawer.tsx:495`, `myTime.ts`): delete it.
- **Kept:** the drawer's finish → hours helper. It is how a worker says "9 till 10" without counting.

### Rule 6: the app knows the breaks; staff can forget them *(coded; the fill figures also count the standard day's planned breaks)*
The owner, 2026-11-03: "The breaks are understood already before time is entered." A worker says "6:30 to 11 on this" and forgets the break; the app takes the break out so the customer is not overcharged. Pay runs from clock-in to clock-out, less unpaid breaks.
That already works: `hours_for` and `finish_in_the_day` step over the breaks, and a day with no clock record uses the standard day's planned breaks (`day_breaks`, `_planned_breaks`). So when the break lines are written is left alone. What goes:
- **`_no_room_for`** (`attendance.py:887`). If an entry's typed hours fill its typed span (08:00–09:00 booked as 1h), the standard break is left off the day as "worked through". That is the opposite of the owner's case: the worker forgot the break, he did not work through it. Delete it. The break always goes on, and the entry's hours are what is paid and billed.
- **"Set the day's clock times before adding a break"** (`attendance.py:1011`): delete it (rule 1).
- **The "inside your break" refusal**: already under rule 5.

### Tests (run after all coding)
- **Unit tests that pin deleted behaviour** are deleted or flipped. The searches listed them:
  - `test_attendance.py`: 197, 211, 234-283, 349-390
  - `test_day_submission.py`: 195, 700
  - `test_approval.py`: 450, 598-629
  - `test_workshop_timesheet_api.py`: 643, 717-759
  - `myTime.test.ts`: `overlapsBooked`, marks
- **New unit tests**, each guarding the block it names:
  - an unclocked past day sends, fills and sweeps on the standard day
  - hours longer than the typed span save with the finish moved
  - an entry inside a break saves after it
  - the office sends a worker's day
- **E2E specs changed:**
  - `mobile/workshop-clock.spec.ts`:
    - :135 is an unclocked day sent on the standard hours, with no row written first
    - :157 and :208 no longer expect "Did not clock"
  - `mobile/workshop-my-time.spec.ts`: :581 and :616 drop the late and remote marks
  - `timesheet/approve-time.spec.ts:122`: the office opens a person's history from Approve time and sees a remote clock edit, by whom
- **E2E specs added:**
  - the office sends a worker's fill sheet
  - an entry typed inside a break saves after it
- **Gates:** `uv run pytest`, `npm run type-check`, vitest, then one full `run_e2e.sh --max-failures=0`.
