# 0033 — Version constraints record what passed testing, not what is compatible

The lock file records the version that passed our gates and the constraint records the oldest version still accepted; a release sweep re-locks at latest and re-tests.

## Rules

- Read `pillow>=12.3.0` in `pyproject.toml` as "12.3.0 is the oldest version we still accept", and `uv.lock` as the record of what actually passed the gates — never as "13 is known to break". Nobody tried 13; the bound and the reason for a bound are different facts, and only the bound is written down. The frontend works the same way through `package.json` and `package-lock.json`.
- During a release dependency sweep: re-lock every dependency at the newest published version, run the gates, and raise the floor to what passed. The refreshed lock is the updated test record.
- A version stays behind latest only when something external forces it — an upstream package's own metadata pins it, or the upgrade fails a gate — and the PR records the reason. A constraint below latest therefore always means something genuinely blocked.

## Do not

- **Re-locking within the existing lock during a sweep** — each sweep then moves only as far as the previous one reached, so untested majors accumulate silently and are finally discovered under deadline, bundled with the feature that forced them.
