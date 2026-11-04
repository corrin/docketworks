# Time work: the backlog's last timesheet items

The week's time work after #229 and #230: every timesheet item left in
`docs/rewrite-status.md`, and the owner's open my-time rulings. Payroll and Xero stay in the
backlog (owner, 2026-11-05: timesheets only).

## What changes
- **Done by #230, deleted from the backlog.** Hours past an entry's span: the cost-line
  routes refuse time, and the one writer redraws the finish. `to_decimal` became
  `rate_from_meta`, which raises. A stale `labour_subtype`: `applyJobPick` clears it.
- **The grid's focus handoffs search the grid**, not the page (`SmartTimesheetTable`).
- **One `is_billable` read.** The accounting reports read the flag as a boolean, as the
  timesheet screens do. Every actual time line carries one (0 of 13,709 differ), and a shop
  job's time is never billable, because `CostLine.save` refuses it.
- **My time honours `weekend_timesheets_enabled`** (owner, 2026-11-05).
- **The job picker's data stands** (owner, 2026-11-05): staff may see jobs, estimates and
  charge-out rates, never another person's pay. The picker carries no wage.

## Tests
- E2E `workshop-my-time-view`: a Monday steps back to the Friday and forward again.
- E2E `create-timesheet-entry` and `keyboard-nav`: the grid's Tab chain, which uses the
  focus handoffs.
- Unit: the accounting suite over `is_billable_line`.

## Open issues
(none)
