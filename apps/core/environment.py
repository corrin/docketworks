"""What a database name means, under the dw_<client>_<env> standard.

The single implementation (ADR 0039) of the questions every destructive or
credential-installing tool asks: which safety class is this database, and is
this name safe to point a scrub at? The name is the one signal an agent
cannot usefully spoof — acting on a database requires connecting to it —
which is why classification never reads environment variables (ADR 0048).

Callers on destructive paths call these before acting even when an earlier
layer has already enforced them: checking a precondition is fail-early
(ADR 0015), not a second implementation, so long as the check calls the rule
rather than restating it — which is exactly what this module exists for.

Model-free on purpose: config/settings.py and settings_test import it at
settings-load time, before the app registry exists.
"""

from typing import Literal

DatabaseClass = Literal["test", "nonprod", "prod"]


def database_class(db_name: str) -> DatabaseClass:
    """Classify per the dw_<client>_<env> standard (env ∈ dev/uat/staging/prod).

    ``test`` wins over ``prod``: Django's test runner prefixes the configured
    name with ``test_``, so ``test_dw_msm_prod`` is a synthetic database and
    treating it as production would block the one place tests may run near
    production credentials (the provisioned per-tenant test role).
    """
    if db_name.startswith("test_") or db_name.endswith("_test"):
        return "test"
    if db_name.endswith("_prod"):
        return "prod"
    return "nonprod"


def validate_scrub_db_name(name: str) -> None:
    """Refuse a scrub-database name that could point at a live database.

    Enforced at settings load, so the ``scrub`` alias cannot exist with a bad
    name — and called again by the pipeline and the scrubber immediately
    before their DROP SCHEMA, because a destructive step checks its own
    preconditions rather than trusting that someone upstream did.
    """
    if not name.endswith("_scrub"):
        raise RuntimeError(
            f"SCRUB_DB_NAME ({name!r}) must end in '_scrub' — refusing to "
            "operate on a database that could be a live one."
        )
