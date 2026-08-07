"""The settings module the schema exporter must run under.

Pinned in one place rather than copied into each script (ADR 0039): a script
that read different settings would describe a different API surface.
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
