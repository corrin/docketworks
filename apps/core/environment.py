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

from django.conf import settings

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


class ProductionDatabaseError(ValueError):
    """A tool that must never touch production was pointed at it.

    Fable: a plain ``ValueError`` would have done, and was rejected because
    two callers translate this refusal into their own outcome (a
    ``CommandError``, a non-zero exit) — catching bare ``ValueError`` around
    the call would also catch a genuine bug and report it as a safety
    refusal. A ``ValueError`` subclass keeps the command shells that already
    convert service refusals working unchanged.
    """


def assert_not_production_database(consequence: str) -> None:
    """Refuse to act when the configured database is a production one.

    ``consequence`` says what this particular tool would do there, because
    that is the only part that differs between callers: seeding writes to a
    live organisation, the dev-login script installs publicly known
    passwords, the integration suite writes to real vendors. Which name to
    read, how to classify it and how to word the refusal are the same rule
    every time, and this is its one implementation (ADR 0039).

    Fable: taking the database name as an argument was rejected — a caller
    passes the name it BELIEVES it is connected to, while the configured
    name is what the process will actually open, and the name is the one
    signal a run cannot spoof (ADR 0048).
    """
    db_name = str(settings.DATABASES["default"]["NAME"])
    if database_class(db_name) != "prod":
        return
    raise ProductionDatabaseError(
        f"Refusing to run against production database {db_name}: {consequence}"
    )


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
