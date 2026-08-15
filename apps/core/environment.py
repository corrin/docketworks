"""Classification of a database name under the dw_<client>_<env> standard.

The single implementation (ADR 0039) of the question every destructive or
credential-installing tool asks: which safety class is this database? The
name is the one signal an agent cannot usefully spoof — acting on a database
requires connecting to it — which is why classification never reads
environment variables (ADR 0048).

Model-free on purpose: settings_test imports this at settings-load time,
before the app registry exists.
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
