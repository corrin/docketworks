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

1. **One hours field.** Add `HoursInput` in `features/timesheet/`. It is a text input (`inputMode="decimal"`) that parses
   with `parseHoursInput` and shows `formatHoursDisplay`. It replaces the grid's cell input, the drawer's
   field and the fill sheet's field. `parseHoursInput` gains a blank → `null` mode for the drawer and fill
   sheet, which need "not sized yet" rather than a fallback. Delete the now-false comment at `myTime.ts:5-7`.
2. **One hours rule.** It lives in the writer, `create_entry`/`update_entry`, and is not split across `lay_out_rows` and
   the client clamp (see decision 2).
3. **One write API.** The grid moves to `/job/workshop/timesheets/`:
   - `WorkshopTimesheetEntryRequest` gains `labour_subtype` and `bill_rate_multiplier`, which only the grid sends.
   - Delete `job_service._create_timesheet_entry` / `_update_timesheet_entry`, the `created_from_timesheet` routing in
     `create_cost_line` / `update_cost_line` / `delete_cost_line`, and `TimesheetCreateBody`. Actual time
     on the cost-line endpoints is then refused outright, which closes the unmarked-line hole as well.
   - Regenerate the client.
4. **One write hook.** Merge `useTimesheetEntries`' writes and `useWorkshopEntryWrites` into one hook. It
   keeps the grid's per-day serialisation and optimistic update, and invalidates both key families plus
   `invalidateJobViews`. This also closes the 412-after-grid-edit gap noted in `job/invalidateJobViews.ts:18`.
5. **One copy of each rule:**
   - Rate options: `rateOptionsFor`. The grid adds "unpaid" through a parameter.
   - Bills its time: one `billsItsTime`.
   - Urgent 1.5: server only. The grid sends `bill_rate_multiplier` only when the user changes it.
   - Blank-to-null: `orNull`.
   - The overtime question: one `askOvertimeThenSend(rows, jobId)` used by the grid, the drawer and the fill sheet. It always sends `job_id`; today the fill sheet omits it.
6. **General work:** one hook over the two endpoints, or one endpoint if the sweep can call the my-day one.

Perf posture: this makes no kanban or hot-path change. The grid's optimistic save is kept, and the drawer and fill sheet gain it.

## Open issues (each is the owner's decision unless marked)
1. [x] **Scope** (owner, 2026-11-02): three screens over shared parts.
2. [x] **Hours rule** (owner, 2026-11-02): any 2dp value up to 24h, enforced in the writer. `lay_out_rows` drops its quarter-hour refusal.
3. [x] **Overtime question** (owner, 2026-11-02): it is the same whoever enters the time, so the office grid asks it too, through the same `askOvertimeThenSend`.
   - Hours add up whoever enters them: the worker's 4h plus the office's 3h is 7h.
   - Time of day is only a reminder for the worker. It means nothing for pay or overtime.
4. [x] **Leave** (owner, 2026-11-02): fold `leave_service._create_days` / `_delete_days` into `create_entry` / `delete_entry`.
   - This removes the general writer's last time-line caller, `_reprice_timesheet_line`.
   - Leave is never overtime: `overtime_part` already returns 0 for leave jobs.
5. [x] **Repair commands** (owner, 2026-11-02): they stay, but `create_overtime_entries`, `reclassify_overtime_entries` and `reassign_time_entries` write through `create_entry` / `update_entry`.
   - These are reusable tools: two line a week up with what Xero payroll paid, and one moves entries between people.
   - `_repair_shared.build_repair_time_line` and each command's own pricing are deleted.
   - This closes the backlog item at `docs/rewrite-status.md:171` (1.5x and 2x lines priced at the base wage). The tests that pin that bug (`test_repair_commands.py:234`, `:367`) flip to assert the correct price.
   - The rate constants become one definition. Today they are defined at `workshop_timesheet_service.py:823`, `attendance.py:986` and `day_submission.py:36`.
6. [x] **Estimate and quote grids** (owner, 2026-11-02): use `HoursInput` there too, so there is one hours field app-wide (`CostLineGrid.tsx:356`).
7. *(mine)* The branch `fix/timesheet-writes-one-writer` has its plan fully ticked. This work needs its own branch and PR, and the owner creates the branch.

## Tests
- **E2E (the done gate):**
  - On each of the grid, the drawer and the fill sheet, typing `4h`, `1 1/4` and `3h 30m` books 4, 1.25 and 3.5 hours.
  - In the office grid, an ordinary-rate entry that takes the day past its usual hours asks the overtime question, as the drawer does.
  - Leave booked on a day with General work rebuilds the General work around it.
  - The existing `tests/e2e/timesheet/*` specs stay green, each on its own `BOOKING_WEEKS` week.
- **Unit:**
  - `hours.test.ts` gains the blank → `null` mode.
  - The backend test that the cost-line endpoints now refuse every actual time line (it replaces the routing tests).
  - The workshop endpoint accepts `labour_subtype`/`bill_rate_multiplier`, and refuses a colleague's line for a non-office user.
- **Gates:** `npm run type-check`, `uv run pytest apps/timesheet apps/job`, then the full E2E with `--max-failures=0`.
