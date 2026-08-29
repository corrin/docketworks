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
#
# It asks the APP rather than reading .env. Bash grepping .env restated three
# rules the app owns and disagreed with all three — most seriously, settings
# calls load_dotenv(override=False), so an exported DB_NAME wins and a .env
# grep cannot see the database the run will actually use.
uv run python -m scripts.ops.assert_integration_target

# The ufw lockout-guard repro needs docker with NET_ADMIN (a root-owned
# network namespace) — CI has no docker, same hermeticity rule as the
# vendor credentials above. The script skips itself, loudly, when docker
# is unavailable; run it on a docker host (the UAT box qualifies).
bash scripts/server/test_ufw_lockout_guard.sh

# -p no:randomly and a single worker: these tests share one external tenant, so
# concurrent runs would fight over the same pay run, contact or leave record.
# Slow and correct beats fast and racing.
exec uv run pytest -m integration -p no:cacheprovider -n0 "$@"
