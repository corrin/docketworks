#!/usr/bin/env python
"""Verify the install's XeroApp row was loaded from the per-instance fixture.

Runs after the instance's ``.fixtures/xero_apps.json`` is loaded (rendered
from scripts/server/templates/xero-apps.json.template by
scripts/server/instance.sh's render_xero_apps_fixture) and BEFORE the OAuth
step, so token columns are expected to be null. Asserts that exactly one row
is marked active and that it has a webhook_key set — without the latter,
every Xero webhook delivery 401s and the install silently loses sync feedback
until somebody notices.
"""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.xero.models import XeroApp  # noqa: E402 -- Django must be configured first


def main() -> int:
    active = XeroApp.objects.filter(is_active=True)
    count = active.count()
    if count == 0:
        print(
            "ERROR: No active XeroApp row. Did you run "
            "scripts/server/instance.sh's render_xero_apps_fixture and load "
            "the resulting <instance>/.fixtures/xero_apps.json?"
        )
        return 1
    if count > 1:
        print(f"ERROR: {count} XeroApp rows marked is_active=True; expected exactly 1.")
        return 1

    row = active.first()
    if row is None or not row.webhook_key:
        print(
            "ERROR: Active XeroApp row has webhook_key unset. Set the Xero "
            "webhook signing key in the rendered xero_apps.json fixture and "
            "re-run loaddata."
        )
        return 1

    print(f"XeroApp configured: {row.label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
