#!/usr/bin/env bash
# Blocks the two verification commands that cost minutes and buy nothing a
# faster command would not.
#
# Measured 2026-08-07: a single check was taking 5-8 minutes and being run
# ~20 times per PR, which is most of a working day spent watching a spinner.
# Prose in CLAUDE.md did not stop it; this does.
#
# Escape hatch: prefix the command with FULL_CHECK=1 when you genuinely want
# the slow form (before a freeze, or when the bundle itself is the artifact).
set -euo pipefail

payload=$(cat)
cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')

deny() {
  jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# Deliberate opt-in wins over every rule below.
if [[ "$cmd" == *"FULL_CHECK=1"* ]]; then
  exit 0
fi

# Match only what is being INVOKED, never what is merely mentioned. Two guards:
# quoted strings are dropped, so `git commit -m "fix pytest"` is not a pytest
# run; and the tool must sit at the start of a command segment (or after
# `uv run`), so `grep pytest file` is not one either. Scope detection below
# still reads the original $cmd, since stripping quotes would hide `-k "foo"`.
scan=$(printf '%s' "$cmd" | sed "s/'[^']*'//g; s/\"[^\"]*\"//g")
SEG='(^|[;&|)(]|&&|\|\|)[[:space:]]*'

# (a) `npm run build` is `tsc -b && vite build`. As a correctness check the
# bundle is dead weight; only the type-check tells you anything.
if [[ "$scan" =~ ${SEG}(npm|pnpm|yarn)[[:space:]]+run[[:space:]]+build([[:space:]]|$) ]]; then
  deny "npm run build is 'tsc -b && vite build' — the bundle tells you nothing a type error would not, and it is minutes slower.

Use:  npm run type-check

If you actually need the built bundle (not a check), re-run with FULL_CHECK=1 in front."
fi

# (b) An unscoped full suite. Scoped runs finish in seconds; the full run is
# CI's job (.github/workflows/ci.yml), not the edit loop's.
if [[ "$scan" =~ ${SEG}(uv[[:space:]]+run[[:space:]]+)?pytest([[:space:]]|$) ]]; then
  # Anything that narrows the run is fine: a path, a node id, -k, --lf, -x.
  if ! [[ "$cmd" =~ (apps/|config/|tests/|::|[[:space:]]-k[[:space:]]|--lf|--last-failed|[[:space:]]-x([[:space:]]|$)) ]]; then
    deny "Unscoped full pytest run — ~5 min, and CI already runs the whole suite on every push (.github/workflows/ci.yml).

Scope it instead:
  uv run pytest apps/job            # one app, seconds
  uv run pytest --lf                # only what failed last time
  uv run pytest apps/job/tests/test_kanban.py::TestFoo

-n auto --dist loadscope is already in addopts — never add it by hand.

If you really need the whole suite now, re-run with FULL_CHECK=1 in front."
  fi
fi

exit 0
