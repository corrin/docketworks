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

import os
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


def required_flag(name: str) -> bool:
    """Parse a required boolean environment variable that may not be misspelt.

    ``os.environ`` rather than ``getenv``: the variable is in
    ``REQUIRED_ENV_VARS``, so absence is a crash, never a default. Only the two
    exact spellings parse, because a typo silently enabling Xero writes — or
    silently leaving them enabled — is the failure these flags exist to
    prevent; ``bool("false")`` is ``True``.
    """
    raw = os.environ[name].lower()
    if raw not in {"true", "false"}:
        raise ValueError(f"{name} must be 'true' or 'false', got {raw!r}")
    return raw == "true"


def validate_xero_fake_flag(*, fake: bool, readonly: bool) -> None:
    """Refuse the combination under which the fake Xero must not exist (ADR 0060).

    The fake answers every Xero call from a local table, so a process running
    it against real users would mint ids Xero has never issued straight into
    the mirror. Whether a process serves real users is answered by the
    database name — the one signal a run cannot spoof (ADR 0048) — and that
    refusal is made where the fake is installed, because settings load before
    the database exists. ``DEBUG`` was the earlier proxy and was dropped: a
    server verifies its release with the fake on a copy of its database
    (ADR 0064) and never carries ``DEBUG``.

    ``XERO_READONLY`` is the valve for a local process pointed at production
    (ADR 0050); the fake reaches no Xero at all. Both set is not "extra safe",
    it is two contradictory answers to "where does a Xero call go", and the
    operator has to say which they meant.
    """
    if not fake:
        return
    if readonly:
        raise ValueError(
            "XERO_FAKE=true and XERO_READONLY=true contradict each other: the "
            "readonly valve is for a local process pointed at production, the "
            "fake is for a development stack that reaches no Xero at all. Set one."
        )
