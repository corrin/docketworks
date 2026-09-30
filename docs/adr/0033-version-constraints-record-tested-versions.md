# 0033 — Version constraints record what passed testing, not what is compatible

The version written down is the version that passed the gates; a sweep takes every dependency to
latest, the gates decide, and what passes is frozen.

## Rules

- **The written version is the tested version.** `frontend/package.json` and `pyproject.toml`
  pin every direct dependency exactly (`"2.1.6"`, `pillow==12.3.0`; never a range), and
  `package-lock.json` and `uv.lock` are the freezes that agree with them. Neither file ever
  records "13 is known to break": nobody tried 13, and the bound and the reason for a bound are
  different facts.
- **Upgrade, test, freeze.** A sweep re-locks every dependency, majors included, at the newest
  published version, runs the gates, and freezes what passed.
- **The sweep is weekly and automatic.** `scripts/ops/sweep_dependencies.sh` moves every pin in
  both ecosystems; `.github/workflows/dependency-sweep.yml` runs it and opens one PR that a
  person picks up, and the same script by hand is an out-of-cycle sweep. `docs/dependency-sweep.md`
  is the loop for a red run. Nothing else prompts a bump: a deferral needs no ticket, because
  next week's sweep moves the pin again.
- **The bump PR owns the code the new version demands.** A renamed option, a new lint rule, a
  changed default: that change is made in the same PR, because the gates are the trust boundary
  and green gates are what let a major land. A change one upgrade forces in a second package is
  part of that code and is made too; that a package moves another is never by itself a reason
  to hold either back.
- **A version is held below latest in exactly two cases, and a dated comment beside the pin
  says which.** Either latest was installed and a gate went red, or the change latest demands
  was attempted and proved nontrivial. The measure is the PR's complexity: a bump PR carries
  mechanical changes only, however many packages they touch, and a change that needs design
  is a feature PR that the next sweep waits for. The comment reads:

  `ADR 0033 — deliberately deferring <package> <version> (<YYYY-MM-DD>): <what failed, or what
  the attempted change turned out to need>`

  In `package.json` the `"//"` key holds them, one string per deferral; in `pyproject.toml` a
  `#` block sits above the dependency. Nothing else earns a comment. A `<` cap without a
  deferral is a defect. Every deferral is retried by the next sweep.
- **The resolver owns transitive versions.** A package that stays below latest because
  something upstream pins it is not deferred and gets no comment in either file; the PR body
  lists it. The dependency file records what was tested, never why the resolver chose what it
  chose.

## Do not

- **Re-locking within the existing lock during a sweep** — each sweep then moves only as far as
  the previous one reached, so untested majors accumulate silently and are finally discovered
  under deadline, bundled with the feature that forced them.
- **Ranges as a substitute for a sweep** — `^2.1.4` or `>=2.1.4` lets the lockfile drift to a
  version nobody ran the gates on, and the file no longer says what was tested.
- **One PR per package** — the combination that ships is what the gates must see; five green
  single-bump PRs merged in turn have tested five trees that never existed together.
- **A comment that explains a transitive version** — the dependency file is not a resolver log;
  a note that "X cannot move because Y pins it" describes nothing that was tested and goes
  stale the moment Y moves.
