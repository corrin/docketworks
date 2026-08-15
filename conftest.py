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
    from typing import Any

    from django.db.models import Model
    from django.test import Client
    from psycopg import Connection

    from apps.accounts.models import Staff

PASSWORD = "s3cret-Pass!"


#: The outbound call each vendor is actually reached through, mapped to the
#: name a failure should say. Deliberately the real call sites — the Xero client
#: factory, litellm's own entry point, the requests handle the geocoder holds —
#: rather than our wrapper functions, so a new caller that bypasses a wrapper is
#: still caught.
_VENDOR_ENTRY_POINTS: dict[str, str] = {
    "apps.xero.auth.get_api_client": "Xero",
    "litellm.completion": "the LLM gateway",
    "apps.company.services.geocoding_service.requests": "Google Maps",
}


@pytest.fixture(autouse=True)
def _no_vendor_contact(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any non-integration test that reaches a real external system.

    This is what keeps the suite hermetic — NOT a side-effect suppression flag.
    ``settings_test`` used to hard-set ``XERO_READONLY=true``, which made every
    test run against a write-suppressing fake without saying so, and would have
    made the integration suite report green without touching Xero (ADR 0050).

    Raising beats suppressing because the two failures look nothing alike: a
    suppressed write passes and proves nothing, while this names the test, the
    vendor, and the two ways out.
    """
    if "integration" in request.keywords:
        return
    for target, vendor in _VENDOR_ENTRY_POINTS.items():
        # raising=False: a target is skipped rather than erroring when its
        # module is not importable in this environment, so one optional
        # dependency cannot take the whole suite down.
        monkeypatch.setattr(target, _Refusal(vendor, target), raising=False)


class _Refusal:
    """Stands in for a vendor entry point and reports what reached it.

    A class, not a function: the geocoder holds a ``requests`` MODULE and calls
    ``requests.post``, so the stand-in has to refuse attribute access too, not
    only being called.
    """

    def __init__(self, vendor: str, target: str) -> None:
        self._vendor = vendor
        self._target = target

    def _refuse(self) -> RuntimeError:
        return RuntimeError(
            f"This test reached {self._vendor} via {self._target}. Unit tests inject a "
            f"fake; a test that must call {self._vendor} for real belongs in the "
            "integration suite — mark it `@pytest.mark.integration` and run "
            "./scripts/ops/run_integration_tests.sh (ADR 0050)."
        )

    def __call__(self, *_args: object, **_kwargs: object) -> object:
        raise self._refuse()

    def __getattr__(self, name: str) -> object:
        """Hand back another refusal rather than raising here.

        Only CALLING a vendor is the offence. Raising on attribute access
        breaks ``mock.patch``, which reads the attribute to save the original
        before installing a fake — so a test doing the right thing would fail
        at setup with a message telling it to do the thing it was already
        doing.
        """
        return _Refusal(self._vendor, f"{self._target}.{name}")


#: Credentials an integration test needs, as (app_label, model, natural key).
#: Resolved through Django's app registry rather than imported, so this file
#: stays outside the layer contract the way its docstring describes.
#:
#: Credentials are migrating out of .env and into the database so they can be
#: changed without a deploy, which means this list GROWS. That is the point of
#: keeping it in one place: a new credential model is one row here, not a new
#: mechanism.
_CREDENTIAL_MODELS: tuple[tuple[str, str, str], ...] = (
    ("xero", "XeroApp", "client_id"),
    ("ai", "AIProvider", "name"),
    ("crm", "PhoneProviderSettings", "id"),
)

#: CompanyDefaults is a singleton the test database already seeds, so it is
#: updated in place rather than inserted. These are the columns that identify
#: the Xero org — without them payroll cannot resolve a calendar.
_COMPANY_DEFAULTS_CREDENTIAL_FIELDS = (
    # Which Xero org the token is for. Without it every call raises before it
    # reaches the network, so it is as load-bearing as the token itself.
    "xero_tenant_id",
    "xero_shortcode",
    "xero_payroll_calendar_name",
    "xero_payroll_calendar_id",
    "xero_payroll_start_date",
    "accounting_provider",
)


@pytest.fixture
def integration_credentials(db: None) -> None:  # noqa: ARG001 -- requesting `db` IS the dependency: it gives this fixture the test database to write into
    """Copy vendor credentials from the dev database into the test database.

    Integration tests call real vendors (ADR 0050), which needs real
    credentials — and those live in the database now, not in .env. Copying them
    into pytest's throwaway database keeps the isolation the test database
    exists for: the dev data is read and never written, and everything the test
    does to OUR side rolls back, while the vendor side is the test's own to
    clean up.

    Rejected alternative: pointing the test run at the dev database directly.
    It would give the same credentials and also hand every integration test
    write access to real local data, for no gain — the vendor is the thing
    under test, not our rows.
    """
    import os

    import psycopg
    from django.apps import apps as django_apps
    from django.conf import settings

    source_name = os.environ["DB_NAME"]
    target = settings.DATABASES["default"]
    if target["NAME"] == source_name:
        raise RuntimeError(
            f"Refusing to copy credentials: the test database IS {source_name}. "
            "Integration tests must run against pytest's own database."
        )

    with psycopg.connect(
        dbname=source_name,
        user=str(target["USER"]),
        password=str(target["PASSWORD"]),
        host=str(target["HOST"]),
        port=str(target["PORT"]),
    ) as source:
        for app_label, model_name, natural_key in _CREDENTIAL_MODELS:
            _copy_rows(source, django_apps.get_model(app_label, model_name), natural_key)
        _copy_company_defaults(source, django_apps.get_model("core", "CompanyDefaults"))


def _copy_rows(source: "Connection[Any]", model: "type[Model]", natural_key: str) -> None:
    """Mirror every row of a credential table into the test database."""
    columns = [str(field.column) for field in model._meta.concrete_fields]
    quoted = ", ".join(f'"{column}"' for column in columns)
    with source.cursor() as cursor:
        cursor.execute(f'SELECT {quoted} FROM "{model._meta.db_table}"')  # noqa: S608 -- columns come from the model, not input
        rows = cursor.fetchall()
    if not rows:
        raise RuntimeError(
            f"No {model.__name__} rows in the dev database. Integration tests need real "
            "credentials; configure the integration before writing its test (ADR 0050)."
        )
    for row in rows:
        values = dict(zip(columns, row, strict=True))
        model._default_manager.update_or_create(
            **{natural_key: values[natural_key]}, defaults=values
        )


def _copy_company_defaults(source: "Connection[Any]", model: "type[Model]") -> None:
    """Copy the Xero org identifiers onto the seeded CompanyDefaults singleton."""
    quoted = ", ".join(f'"{field}"' for field in _COMPANY_DEFAULTS_CREDENTIAL_FIELDS)
    with source.cursor() as cursor:
        cursor.execute(f'SELECT {quoted} FROM "{model._meta.db_table}" LIMIT 1')  # noqa: S608 -- fields are module constants
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("The dev database has no CompanyDefaults row to copy Xero config from.")
    # The seeded singleton, reached through the manager rather than get_solo:
    # this module resolves models through the app registry, so it holds a
    # plain Model type with no knowledge of solo-model helpers.
    defaults = model._default_manager.get()
    for field, value in zip(_COMPANY_DEFAULTS_CREDENTIAL_FIELDS, row, strict=True):
        setattr(defaults, field, value)
    defaults.save(update_fields=list(_COMPANY_DEFAULTS_CREDENTIAL_FIELDS))


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
