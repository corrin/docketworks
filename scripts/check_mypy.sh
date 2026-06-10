#!/bin/bash
# Authoritative backend type check (KAN-205).
# Runs full-strict mypy and fails on any error not recorded in mypy-baseline.txt.
# After fixing baselined errors, shrink the baseline with:
#   poetry run mypy apps/ docketworks/ | poetry run mypy-baseline sync
#
# mypy exits 1 whenever the (baselined) errors exist, so its exit code is not
# the gate — mypy-baseline filter's is. We still guard against mypy crashing
# (config error, plugin failure) by requiring its end-of-run summary line.
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# || true: mypy exits 1 on the normal baselined-errors path; the summary-line
# guard below is what detects a crash. 2>&1 so crash output lands in $out.
out="$(poetry run mypy apps/ docketworks/ 2>&1 || true)"
if ! grep -qE '^(Found [0-9]+ errors?|Success: no issues)' <<< "$out"; then
    printf '%s\n' "$out"
    echo "check_mypy: no mypy summary line found — mypy crashed; failing." >&2
    exit 2
fi

printf '%s\n' "$out" | poetry run mypy-baseline filter
