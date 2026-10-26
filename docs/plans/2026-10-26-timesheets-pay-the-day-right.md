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

- [ ] Edits through the cost-line endpoint (office grid) don't rebuild a filled day's General work
- [ ] A public holiday (office closure) is missed for someone whose day was already full, so their time that day isn't paid at 1.5×
- [ ] The General work rebuild locks jobs out of id order; prove or rule out a deadlock against a sweep
- [ ] A split overtime line's pay item isn't asserted
- [ ] Office-grid writes save times without checking them (a stop before the start, more hours than the span)
- [ ] Check whether these from the reverted model still hold: a standard break skipped because he worked through it doesn't come back when that entry is deleted; the fill-day sheet doesn't warn of overtime before sending
- [ ] Owner's question: Job Y typed over Job X currently saves both with an overlap warning, as on main. Recommendation: keep it (two things at once is real, and both are billed)
- [ ] gettext 0.23.2 on the dev machine, and CI pinned to `ubuntu-26.04` to match production (recommended; needs the owner's yes)
- [ ] Fresh review of `main...HEAD`
- [ ] Full E2E green with `--max-failures=0` (blocked: the owner runs `powercfg.exe /change standby-timeout-ac 0` first)
- [ ] `docs/rewrite-status.md` and `docs/rewrite-history.md` updated
