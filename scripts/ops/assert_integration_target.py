#!/usr/bin/env python
"""Refuse an integration run pointed somewhere it must never write.

Opus: ``run_integration_tests.sh`` used to answer this in bash, by grepping ``.env``.
That was three restatements of rules the app already owns, and all three had
drifted from them:

- it read ``DB_NAME`` out of ``.env``, but ``config/settings.py`` calls
  ``load_dotenv(override=False)``, so an EXPORTED ``DB_NAME`` wins and was
  invisible to the guard — the run could point at production while the guard
  approved the file;
- it classified with ``*_prod``, while ``apps.core.environment.database_class``
  gives ``test`` precedence, so ``test_dw_msm_prod`` (what Django's test runner
  produces near production credentials) was refused by the script and allowed
  by the app;
- it matched ``^XERO_READONLY=true`` literally, while settings lowercases the
  value — ``XERO_READONLY=TRUE`` passed the script and set readonly ON, quietly
  suppressing the writes the suite exists to prove.

So this asks the app instead. ``apps/core/environment.py`` says when that is
the right shape: "checking a precondition is fail-early (ADR 0015), not a
second implementation, so long as the check calls the rule rather than
restating it." There is no fallback here and nowhere else to look: if the app
cannot answer, ``validate_required_settings`` fails loudly and the run stops.

The Xero TENANT half of ``assert_not_production_target`` is deliberately not
called here — it resolves a live token, and a pre-flight should not require the
network to tell an operator their database is wrong. The integration tests call
that guard themselves, per test, where a refusal is reported against the test
that caused it.

Usage:
    uv run python -m scripts.ops.assert_integration_target
"""

import sys

from scripts.bootstrap import setup_django

setup_django()

from django.conf import settings  # noqa: E402 -- Opus: Django must be configured first

from apps.core.environment import (  # noqa: E402
    ProductionDatabaseError,
    assert_not_production_database,
    database_class,
)
from apps.xero.operator_guards import assert_xero_writes_enabled  # noqa: E402


def main() -> int:
    """Refuse a production database or a write-suppressed run."""
    try:
        assert_not_production_database("integration tests write to real vendors.")
    except ProductionDatabaseError as exc:
        print(f"Refusing to start: {exc}", file=sys.stderr)
        return 1

    try:
        assert_xero_writes_enabled("the integration suite")
    except RuntimeError as exc:
        print(f"Refusing to start: {exc}", file=sys.stderr)
        return 1

    db_name = str(settings.DATABASES["default"]["NAME"])
    print(f"Integration target: {db_name} ({database_class(db_name)}), Xero writes enabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
