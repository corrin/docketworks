#!/usr/bin/env bash
# Run the integration suite: the tests that call real external systems (ADR 0050).
#
# These are a MERGE GATE. The default `uv run pytest` deselects them
# (`-m 'not integration'` in pyproject) because CI has no sandbox credentials and
# must stay hermetic; this script is how they actually get run.
#
# Unlike run_e2e.sh this owns no services. Integration tests drive services and
# providers directly, so they need Django, the database and credentials — not a
# browser, a frontend build, Celery or ngrok. Database writes land in pytest's
# throwaway test database; only the vendor calls touch anything real, which is
# the whole point.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Refuse a production target before importing anything that could reach out.
# The per-test guards in apps/xero/operator_guards.py are the real enforcement;
# this is the early, obvious refusal so an operator is told at the prompt rather
# than in a stack trace.
DB_NAME="$(grep -E '^DB_NAME=' .env 2>/dev/null | cut -d= -f2- || true)"
if [[ "$DB_NAME" == *_prod ]]; then
  echo "Refusing to start: DB_NAME '$DB_NAME' names a production database." >&2
  exit 1
fi
if grep -qE '^XERO_READONLY=true' .env 2>/dev/null; then
  echo "Refusing to start: XERO_READONLY=true suppresses the writes these tests exist to prove." >&2
  exit 1
fi

# -p no:randomly and a single worker: these tests share one external tenant, so
# concurrent runs would fight over the same pay run, contact or leave record.
# Slow and correct beats fast and racing.
exec uv run pytest -m integration -p no:cacheprovider -n0 "$@"
