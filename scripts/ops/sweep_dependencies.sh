#!/usr/bin/env bash
#
# The dependency sweep (ADR 0033): every direct dependency, both ecosystems, to its newest
# published version, pinned exactly at that version. It moves pins and lockfiles only; running
# the gates, handling a red run and merging are a person's job, per docs/dependency-sweep.md.
#
# .github/workflows/dependency-sweep.yml runs exactly this every week and opens one PR from the
# result; run it by hand, on a fresh branch from main, for an out-of-cycle sweep. Stdout is the
# report the PR body carries.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

snapshot_frontend() {
  python3 - <<'PY'
import json
with open("frontend/package.json") as handle:
    package = json.load(handle)
for section in ("dependencies", "devDependencies"):
    for name, version in sorted(package.get(section, {}).items()):
        print(f"{name} {version}")
PY
}

# Two `name version` snapshots in, a Markdown table of what moved out.
report_moves() {
  BEFORE="$1" AFTER="$2" python3 - <<'PY'
import os
before = dict(line.split(" ", 1) for line in os.environ["BEFORE"].splitlines() if line)
after = dict(line.split(" ", 1) for line in os.environ["AFTER"].splitlines() if line)
moved = [(name, before.get(name, "—"), after[name]) for name in sorted(after) if before.get(name) != after[name]]
if not moved:
    print("Nothing moved: every direct dependency was already at latest.")
else:
    print("| package | from | to |")
    print("|---|---|---|")
    for name, old, new in moved:
        print(f"| {name} | {old} | {new} |")
PY
}

echo "# Weekly dependency sweep"
echo
echo "Every direct dependency at its newest published version, pinned there (ADR 0033)."
echo "Green: merge. Red: the loop in docs/dependency-sweep.md. A pin this sweep moved that"
echo "a gate rejects goes back to its previous version with a dated deferral beside it."
echo

before_frontend=$(snapshot_frontend)
(cd frontend && npx --yes npm-check-updates --target latest -u >/dev/null)
(cd frontend && npm install --no-fund --no-audit >/dev/null)
# Transitive advisories move within what the exact pins allow. The audit's exit code is its
# finding count, not a verdict on the sweep (the commit tier gates at high), so it is told not
# to fail the run.
(cd frontend && npm audit fix --audit-level=none >/dev/null)
after_frontend=$(snapshot_frontend)
echo "## Frontend"
echo
report_moves "$before_frontend" "$after_frontend"
echo

before_python=$(python3 scripts/ops/pin_pyproject.py show)
python3 scripts/ops/pin_pyproject.py relax >/dev/null
uv lock --upgrade --quiet
python3 scripts/ops/pin_pyproject.py pin >/dev/null
uv lock --quiet
after_python=$(python3 scripts/ops/pin_pyproject.py show)
echo "## Python"
echo
report_moves "$before_python" "$after_python"
echo

uv sync --quiet
echo "### Below latest after the sweep"
echo
echo "The resolver's choice, held there by another package's metadata; not a deferral and not"
echo "commented in the file (ADR 0033)."
echo
echo '```'
uv pip list --outdated 2>/dev/null || echo "(uv pip list --outdated reported nothing)"
echo '```'
echo

echo "### pip-audit"
echo
echo "Advisory. A package listed here is one the swept tree still cannot reach."
echo
echo '```'
# deliberate-swallow: pip-audit exits with its finding count, and the findings are the report.
set +e
uv run --with pip-audit python -m pip_audit 2>&1
set -e
echo '```'
