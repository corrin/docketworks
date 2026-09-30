# The dependency sweep

Upgrade everything, test, freeze the tested version. ADR 0033 is the rule; this is the procedure.

## What runs on its own

Every Sunday 20:00 UTC (Monday morning NZ), `.github/workflows/dependency-sweep.yml` runs
`scripts/ops/sweep_dependencies.sh` on main and opens one PR, **Weekly dependency sweep**, on
branch `chore/weekly-dependency-sweep`. The script takes every direct dependency in
`frontend/package.json` and `pyproject.toml` to its newest published version, pins it exactly
there, re-locks both lockfiles, and writes the PR body: what moved, what the resolver still
holds below latest, and the pip-audit report. It opens nothing when nothing moved.

The PR is a prompt, not a verdict. CI does not run on the bot's own commit (GitHub suppresses
triggers from `GITHUB_TOKEN`); it runs on the first push a person makes to the branch.

While a sweep PR is open, the weekly run does nothing: the action rebuilds the branch from main
on every run, which would discard the commits a person made on it. Merge or close the open
sweep and the next run proceeds, so a sweep left open costs exactly the weeks it stays open.

## Picking it up

1. Check the branch out, run the commit tier, `npm run type-check`, `npx vitest run`, `uv run
   mypy` and `FULL_CHECK=1 uv run pytest`. Run vitest and pytest one after the other, not
   together: the two suites contend for CPU and the contention produces false failures.
2. **Green: merge.** E2E runs once per release, not per sweep.
3. **Red: the loop below**, then push; CI re-judges.

## The red loop

One decision per commit, on the sweep branch.

1. **Bisect to the one package.** Restore its previous pin (the PR body's "from" column),
   reinstall (`npm install` / `uv lock` then `uv sync`), re-run the failing gate. Green with one
   package restored names the package.
2. **Mechanical fix: make it, keep the version.** A renamed option, a new lint rule's hoists, a
   changed default. The bump PR owns this code, however many files it touches, and a change one
   upgrade forces in a second package is part of it.
3. **Otherwise: restore the pin and say why, dated.** The comment form is in ADR 0033:
   `ADR 0033 — deliberately deferring <package> <version> (<YYYY-MM-DD>): <what failed, or what
   the attempted change turned out to need>`. In `package.json` it is one string in the `"//"`
   list; in `pyproject.toml` a `#` block above the dependency. The measure is the PR's
   complexity: a sweep carries mechanical changes only, and a change that needs design is a
   feature PR the next sweep waits for.
4. Nothing else earns a comment. A package the resolver leaves below latest because something
   upstream pins it is listed in the PR body and nowhere else.

A deferral needs no ticket: next week's sweep moves the pin again, and if the gate is still red
the same loop restores it. The dated comment is the record, and a deferral older than a few
sweeps is a question for the owner, not a chore for the sweep.

## By hand

On a fresh branch from main, from the repository root:

```
scripts/ops/sweep_dependencies.sh
```

Then the gates, the commit and push tiers, and a PR. This is exactly what the workflow runs.

## Facts the design rests on

- Dependabot's pip ecosystem only proposes changes to `pyproject.toml`: it never sees a
  transitive package, and never a version the declared range already admits. That blind spot
  once let a Django security release and eleven other advisories sit in `uv.lock` unnoticed,
  and later hid an openai-agents release the resolver could not take. Dependabot keeps only the
  `github-actions` ecosystem here.
- One PR per package never tests the combination that ships. The sweep is one PR.
- `scripts/ops/pin_pyproject.py` is the only thing that rewrites Python pins: `relax`, `uv lock
  --upgrade`, `pin`. A spec with a `<` cap stops it, because ADR 0033 wants a dated deferral for
  any bound that is not the tested version.
