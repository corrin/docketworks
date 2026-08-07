"""The settings module every schema script must run under.

`scripts/checks/export_openapi.py` writes `frontend/schema.v2.yml` and
`scripts/checks/schema_parity_diff.py` compares the live schema against v1's frozen
contract. If those two read different Django settings they could describe
different API surfaces, and the parity diff would be guarding a schema the
frontend never generates from — so the pin lives here once rather than being
copied into each script (ADR 0039, ADR 0044).

`config.settings` is the wrong choice for both: it demands the full runtime
environment (SECRET_KEY, DB_*, REDIS_URL...), which is why CI's "exported
schema is current" step died on every run and never actually checked anything.
Output is verified byte-identical under both modules, so this is a guard
against drift rather than a fix for a live difference.
"""

import os

SETTINGS_MODULE = "config.settings_test"


def pin_settings() -> None:
    """Set DJANGO_SETTINGS_MODULE, refusing an inherited value that disagrees.

    `setdefault` would let an exported DJANGO_SETTINGS_MODULE win silently and
    reintroduce both problems above, so a conflicting value is an error rather
    than a preference (ADR 0015).
    """
    inherited = os.environ.get("DJANGO_SETTINGS_MODULE")
    if inherited is not None and inherited != SETTINGS_MODULE:
        raise RuntimeError(
            f"DJANGO_SETTINGS_MODULE is {inherited!r}; the schema scripts require "
            f"{SETTINGS_MODULE!r} so that the exported schema and the parity diff "
            "describe the same API surface."
        )
    os.environ["DJANGO_SETTINGS_MODULE"] = SETTINGS_MODULE
