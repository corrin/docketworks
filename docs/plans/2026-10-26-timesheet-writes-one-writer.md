# Every write of a person's time goes through the one entry writer (follow-up to PR #228)

## Goal
PR #228 merged with five commits no reviewer had seen (5bbec5e0..fc680511). A
read-only review of them on 2026-10-26 found that the owner's rule, "Non-office
Staff should not be able to READ or WRITE another staff member's timesheets",
still has a hole on writes, plus four smaller defects. Fix each test-first.

## Open issues
Everything found goes here the moment it's found. The PR merges when this list is empty.

- [x] The full E2E run of PR #228 (2026-10-26, `logs/recovered/e2e-full-2026-10-26.log`): 215 passed, 7 failed, 23 did not run; each failure is below
- [x] E2E: "E2E Test" and "E2E Office" are employed from 2026-10-17 (created before the fixture command set a start date on 2026-10-18; the payroll seed carried it into dev Xero), so specs booking earlier days are refused (workshop-my-time-view:184, mobile workshop-my-time:205 on android and iphone). Xero owns a linked login's start date (test_a_linked_login_keeps_the_start_date_xero_gave_it), so the command stays as it is: the two dev-database rows are set to 2020-01-01, the fixture's date, which the fake is seeded from
- [ ] Blocked on the owner: in the dev Xero tenant, set the "E2E Test" and "E2E Office" employees' start date to 2020-01-01, or a real-Xero run's staff sync copies 2026-10-17 back
- [x] E2E: keyboard-nav:111 and urgent-job-defaults:65 booked on the latest weekday, which other specs' time takes past 8h, so the entry split at overtime: each has a weekday of its own (10 and 11 weeks back)
- [x] E2E: general-work-sweep:115 sweeping everyone (12 people) took 8.1s against the spec's 5s wait (5.45s before #228; it failed on 2026-10-20 and -24 too). Approval-only saves skip the line's checks and sums (38 to under 6 queries a line), and a line no longer re-saves its job's latest cost set: 6.2s. The spec waits for the sweep's answer, then reads the message
- [ ] E2E: job-rejection:22 times out at line 78: after a cancel, reopening the rejection dialog leaves an open dialog overlay that intercepts the click on "Reopen in Draft". Intermittent since 2026-10-20 (before #228); a real dialog defect
- [ ] Full E2E green with `--max-failures=0` on this branch
- [ ] Owner's call: sweeping everyone (12 people) takes 6.2s, against 5.45s before #228; most of what is left is `full_clean` on every new line (about 27 queries a line, its database constraints and foreign keys checked by query). Recommendation: leave it for now (6 staff take about 3s), and revisit if the office finds it slow
- [x] A time line in actual costs that does not carry `meta.created_from_timesheet` skips the entry writer: a non-office worker can POST `kind="time"` with a colleague's `staff` to the cost-line endpoint, and it becomes the colleague's paid hours with no owner check, placement, overtime or General work rebuild. A PATCH can turn a material line into a colleague's time. Every time line in actual costs goes to the workshop entry service; the generic writer refuses `kind` and `staff` changes that would make one (`apps/job/services/job_service.py` `create_cost_line`, `_update_cost_line`): both proven (201 and 200), both refused now
- [x] The full job's ETag is `job.updated_at` alone, though the body now depends on who reads it: not a defect. Django's session and CSRF middleware already send `Vary: Cookie`, so a browser keeps each reader's copy apart; the ETag stays the edit check (`If-Match`)
- [x] `refill_general_work`'s "unchanged" check compares joined stretches, so two overlapping General work lines over one gap compare equal and are paid twice: the lines' own minutes must add up to the joined ones (R17)
- [x] `_overtime_is_off` allows a quarter hour either way, which hides a real mismatch under 15 minutes: compared exactly against the day's overtime with the split rule applied (E13e; the rule is one function, `split_off`)
- [x] `overtime_part(job_id=None)` reads as the Break job when none is set up (`None == None`), so placement before a job is picked says no overtime (E4c)
