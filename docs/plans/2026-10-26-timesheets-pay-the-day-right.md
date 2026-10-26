# Timesheets pay the day right (PR #228)

## Goal
Timesheets pay the day right (owner rulings 2026-10-25 and 2026-10-26, in `docs/rewrite-history.md`):
- Standard breaks go only on the free part of a day and never change an entry.
- Time past 8 hours worked is overtime, and the office is told when a sweep or entry makes some.
- Leave is booked in whole days and fills what's left of each day; time on a leave job is never overtime.
- General work is a flag on the day: the time on no job and no break is General work, rebuilt whenever the day changes. Anyone can put the rest of their own day on it.
- Entering is not approving: time waits for approval whoever enters it, any change to approved time takes the approval off, and staff can change their own approved time.

## Open issues
Everything found goes here the moment it's found. The PR merges when this list is empty.

- [x] Edits through the cost-line endpoint (office grid) don't rebuild a filled day's General work: the grid's time now goes through the workshop entry service, the one writer of a person's time
- [x] A public holiday missed for someone whose day was already full: not a defect, Joe enters 1.5× himself (owner, 2026-10-26)
- [x] An office closure on a day that already has time entered is refused, saying so (owner, 2026-10-26)
- [x] The General work rebuild locks jobs out of id order; prove or rule out a deadlock against a sweep: real (an entry held its job and waited for General work, a sweep the reverse); an entry now locks both in one id-ordered step
- [x] A split overtime line's pay item isn't asserted: E1b, which fails when the overtime piece posts as Ordinary Time
- [x] Office-grid writes save times without checking them (a stop before the start, more hours than the span): fixed by the same change
- [x] Found: the office grid skipped the employment-dates rule; fixed by the same change
- [x] The fill-day sheet doesn't warn of overtime before sending: it now asks as the entry drawer does (one shared dialog)
- [x] A standard break skipped because he worked through it doesn't come back when that entry is deleted: confirmed, and left as it is (owner, 2026-10-26); the office sees the hours at approval
- [x] Job Y typed over Job X: both saved and billed, with the overlap warning (owner, 2026-10-26)
- [x] CI pinned to `ubuntu-26.04`, production's release (owner, 2026-10-26)
- [x] Found: through the office grid's endpoint any staff member could create time for a colleague; the entry owner rule now applies (owner, 2026-10-26)
- [x] Non-office staff read no one else's time, through any endpoint (owner, 2026-10-26): the job, its actual costs and its timeline now show them only their own time lines; the timesheet, leave and report reads were already office-gated or owner-checked; the job sheet's per-person totals stay (owner)
- [ ] Blocked on the owner: upgrade the dev machine to Ubuntu 26.04 (`! sudo do-release-upgrade`), so its gettext is production's 0.23.2
- [x] Fresh review of `origin/main...HEAD` (2026-10-26); its findings:
- [x] Review 1: a filled day whose General work is split at overtime is deleted and recreated on every write, so its approval and any office change to it are lost: the rebuild compares joined stretches (R14)
- [x] Review 2: changing the wage on an urgent job's entry drops its charge from 1.5x to 1.0x (the office grid now reaches this path): a re-derived charge keeps the urgent 1.5x (F1b); it was wrong from the drawer on main too
- [x] Review 3: "Overtime to check" flags a day under a quarter hour past 8h, which the split leaves ordinary; the placement endpoint's overtime figure ignores the same rule and leave jobs: the check allows the quarter hour (E13d); placement answers through overtime_part with the drawer's job (E4b)
- [x] Review 4: migration 0013 flags nothing: false, the review read a stale local `main`; `origin/main` stamps the sweep source
- [x] Review 5: booked leave blocks an office closure: correct, the office deletes that leave first (owner, 2026-10-26)
- [x] Review 6: editing or cancelling a leave request doesn't take the person's lock, so it can race a sweep: editing already did (its joined lock); cancelling now does (test_leave_concurrency)
- [x] Review 7: a sweep on a worked public holiday says "has done over 8h" whatever the hours: it now says he worked a public holiday (R15)
- [x] Review: job migration 0018's CHECK constraint: not this branch's; it is on production already and has run there
- [ ] Full E2E green with `--max-failures=0` (blocked: the owner runs `powercfg.exe /change standby-timeout-ac 0` first)
- [ ] `docs/rewrite-status.md` and `docs/rewrite-history.md` updated
