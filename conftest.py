"""The minimum installation every test runs against.

DocketWorks cannot boot without a CompanyDefaults row and cannot do anything
without a Staff, so a test that starts from an empty database is exercising a
state the product never runs in. That default made three separate things go
wrong: `get_solo()` blew up on a column instead of answering, one test asserted
behaviour for an impossible scenario, and tests for bottom-layer routers had to
move away from their own code to reach a fixture.

Two facts make this file the right home for the WIRING. import-linter's
``root_packages`` are ``apps`` and ``config``, so a top-level conftest sits
outside the layer contract and may import anything; and pytest resolves fixtures
by NAME, not by import, so ``apps/ai/tests`` can have a Staff without
``apps.ai`` importing ``apps.accounts``. The layering problem disappears rather
than being dodged.

The seeding itself lives in ``apps/company/tests/job_fixtures.py`` beside the
factories that depend on it. Defining it here as well is how this file briefly
had a second copy of the pay-item catalogue — two definitions that had to agree,
in the very file written to stop that happening (ADR 0039).

A test may opt out with ``bare_install`` and start from nothing, but there is
little reason to: provisioning creates AND seeds the database in one step, so
"created but unseeded" is not a state a real instance passes through. The escape
hatch exists so the scenario is not banned, not because it is expected.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    # Real types without importing models at collection time, which would run
    # before Django's app registry is populated.
    from django.test import Client

    from apps.accounts.models import Staff

PASSWORD = "s3cret-Pass!"


@pytest.fixture(autouse=True)
def _docketworks_prereqs(request: pytest.FixtureRequest) -> None:
    """Give every database test an installation that could actually boot.

    Guarded on the ``django_db`` marker so a pure-unit test pays nothing, and
    on ``bare_install`` so provisioning tests still start from empty.
    """
    if "django_db" not in request.keywords or "bare_install" in request.keywords:
        return
    # Imported here, not at module scope: collection runs before Django's app
    # registry is populated and job_fixtures imports models.
    from apps.company.tests.job_fixtures import seed_docketworks_prereqs

    seed_docketworks_prereqs()


@pytest.fixture
def office_staff() -> "Staff":
    """A staff member who may act on jobs. The default actor."""
    from apps.accounts.models import Staff

    return Staff.objects.create_user(
        email="office@example.test",
        password=PASSWORD,
        first_name="Office",
        last_name="Staff",
        is_office_staff=True,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.fixture
def superuser() -> "Staff":
    """A superuser.

    ``is_office_staff`` is not optional: create_superuser refuses a superuser
    who cannot act as office staff, so in v2 a superuser is always a strict
    superset of one.
    """
    from apps.accounts.models import Staff

    return Staff.objects.create_superuser(
        email="super@example.test",
        password=PASSWORD,
        first_name="Super",
        last_name="User",
        is_office_staff=True,
    )


def _authenticated(staff: "Staff") -> "Client":
    """A client carrying the HttpOnly access-token cookie a browser would."""
    from django.test import Client
    from ninja_jwt.tokens import RefreshToken

    from apps.core.auth import jwt_cookie_config

    client = Client()
    refresh = RefreshToken.for_user(staff)
    client.cookies[jwt_cookie_config().access_name] = str(refresh.access_token)
    return client


@pytest.fixture
def api(office_staff: "Staff") -> "Client":
    """An authenticated office-staff client. The default caller.

    Named ``api`` rather than shadowing pytest-django's ``client``, so a test
    that wants an ANONYMOUS client can still ask for ``client`` and mean it.
    An authenticated fixture called ``client`` is exactly how an auth test
    silently stops testing auth — which happened to one of mine.
    """
    return _authenticated(office_staff)


@pytest.fixture
def superuser_api(superuser: "Staff") -> "Client":
    """An authenticated superuser client, for the wider-visibility paths."""
    return _authenticated(superuser)
