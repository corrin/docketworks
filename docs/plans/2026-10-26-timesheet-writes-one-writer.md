# Every write of a person's time goes through the one entry writer (follow-up to PR #228)

## Goal
PR #228 merged with five commits no reviewer had seen (5bbec5e0..fc680511). A
read-only review of them on 2026-10-26 found that the owner's rule, "Non-office
Staff should not be able to READ or WRITE another staff member's timesheets",
still has a hole on writes, plus four smaller defects. Fix each test-first.

## Open issues
Everything found goes here the moment it's found. The PR merges when this list is empty.

- [x] The full E2E run of PR #228 (2026-10-26, `logs/recovered/e2e-full-2026-10-26.log`): 215 passed, 7 failed, 23 did not run; each failure is below
- [ ] E2E: "E2E Test" and "E2E Office" are employed from 2026-10-17 (made before the fixture command set a start date, which it only sets on create; the payroll seed carried it into dev Xero), so specs booking earlier days are refused (workshop-my-time-view:184, mobile workshop-my-time:205 on android and iphone). `e2e_ensure_fixtures` ensures the start date on existing users too
- [ ] Blocked on the owner: in the dev Xero tenant, set the "E2E Test" and "E2E Office" employees' start date to 2020-01-01, or a real-Xero run's staff sync copies 2026-10-17 back
- [ ] E2E: keyboard-nav:111 and urgent-job-defaults:65 read the office grid's create answer as the whole entry; it is now the first piece of a split entry (1.5h of 2h; the 1.5x piece of an urgent entry)
- [ ] E2E: general-work-sweep:115 waits for "booked to General work." after sweeping everyone; the message never shows
- [ ] E2E: job-rejection:22 timed out waiting for a job PATCH response
- [ ] A time line in actual costs that does not carry `meta.created_from_timesheet` skips the entry writer: a non-office worker can POST `kind="time"` with a colleague's `staff` to the cost-line endpoint, and it becomes the colleague's paid hours with no owner check, placement, overtime or General work rebuild. A PATCH can turn a material line into a colleague's time. Every time line in actual costs goes to the workshop entry service; the generic writer refuses `kind` and `staff` changes that would make one (`apps/job/services/job_service.py` `create_cost_line`, `_update_cost_line`)
- [ ] The full job's ETag is `job.updated_at` alone, though the body now depends on who reads it: a shared browser could be answered 304 with the office's copy. The ETag includes the reader (`apps/job/api.py` `get_full_job`, `_current_job_etag`)
- [ ] `refill_general_work`'s "unchanged" check compares joined stretches, so two overlapping General work lines over one gap compare equal and are paid twice. Also require the lines' own hours to add up to the gaps' (`workshop_timesheet_service.py`)
- [ ] `_overtime_is_off` allows a quarter hour either way, which hides a real mismatch under 15 minutes (8.5h split 8 + 0.5 at 1.5x, then a 0.2h ordinary entry deleted: 0.2h stays at 1.5x, unflagged). Compare exactly against the day's overtime with the split rule applied, not with a margin (`approval.py`)
- [ ] `overtime_part(job_id=None)` reads as the Break job when none is set up (`None == None`), so placement before a job is picked says no overtime (`workshop_timesheet_service.py`)
