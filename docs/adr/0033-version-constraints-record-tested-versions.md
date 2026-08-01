# 0033 — Version constraints record what passed testing, not what is compatible

Every declared dependency bound is a record of the newest version that passed our tests, so a release sweep ignores the bounds and re-tests at latest.

## Problem

`pillow = "^12.1.1"`, `holidays = ">=0.93,<0.101"`, and `prettier: "3.8.3"` all look like compatibility limits — as though 13, 0.101, and 3.9 were tried and rejected. They were not. Each records the newest version available the last time we swept dependencies. Reading them as compatibility boundaries makes an upgrade look risky when nobody has ever tested the newer version, and a sweep that respects them can only ever move within the last sweep's ceiling.

## Decision

Treat every version constraint as a test record, never as evidence of incompatibility. During a release dependency sweep, ignore the declared bounds: widen each constraint to the newest published version, re-lock, and run the gates. A version stays behind latest only when something external forces it — an upstream package's own published metadata pins it, or the upgrade fails a gate. Record that reason in the PR. When a constraint is widened and the gates pass, the new bound becomes the updated test record.

## Why

The bound and the reason for the bound are different facts, and only the bound is written down. Once they are conflated, dependency debt compounds silently: each sweep respects the previous sweep's ceiling, so majors accumulate untested behind carets that were never a judgement about anything. Testing is the only thing that produces real evidence, and it is cheap and automated here — so the honest default is to move everything to latest and let the gates speak. That also keeps the expensive signal, an actual failure, distinguishable from the absence of signal.

## Alternatives considered

- **Conservative carets, upgrade on demand:** the common default — take patches automatically, majors only when a feature needs one. Sensible where upgrades are risky or the test suite is thin. Here it guarantees that majors are only ever discovered under deadline, bundled with the feature that forced them, which is the worst time to debug a breaking change.
- **Pin everything exactly and never sweep:** maximum reproducibility, and correct for a system that must not change. It converts every eventual upgrade into an archaeology exercise across years of releases at once, and leaves security advisories unpatched by default.
- **Automated per-PR bumps only (dependabot merged as it opens them):** keeps the lag near zero without a sweep. It cannot resolve interlocked upgrades — the cases where a bump is only possible alongside another package's — which is exactly where the debt collects.

## Consequences

Dependency lag stays near zero and majors surface one at a time, on a schedule, with the whole test suite as the arbiter. The cost is a real testing burden every release, and sweeps that occasionally have to back a version out. A constraint below latest becomes meaningful: it means something genuinely blocked, and the PR says what.
