# 0033 — Version constraints record what passed testing, not what is compatible

Every dependency bound records the newest version that passed our gates; a release sweep ignores the bounds and re-tests at latest.

## Rules

- Read `pillow = "^12.1.1"` as "12.1.1 is the newest version we have tested" — never as "13 is known to break". Nobody tried 13; the bound and the reason for the bound are different facts, and only the bound is written down.
- During a release dependency sweep: widen every constraint to the newest published version, re-lock, run the gates. When a widened constraint passes, the new bound is the updated test record.
- A version stays behind latest only when something external forces it — an upstream package's own metadata pins it, or the upgrade fails a gate — and the PR records the reason. A constraint below latest therefore always means something genuinely blocked.

## Do not

- **Respecting the existing bounds during a sweep** — each sweep then moves only within the previous sweep's ceiling, so untested majors accumulate silently and are finally discovered under deadline, bundled with the feature that forced them.
