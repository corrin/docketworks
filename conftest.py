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
    from collections.abc import Iterator
    from typing import Any

    from django.db.models import Model
    from django.test import Client
    from psycopg import Connection

    from apps.accounts.models import Staff

PASSWORD = "s3cret-Pass!"


#: Opus: The outbound call each vendor is actually reached through, mapped to the
#: name a failure should say.
#:
#: Every entry must survive `from x import y`. A patch replaces one name in one
#: namespace, so patching a FUNCTION only stops callers that look it up through
#: its defining module at call time. `apps.xero.auth.get_api_client` was such an
#: entry, and thirteen modules bind it at import — `payroll_push`, `sync`,
#: `contacts`, `provider`, `transforms`, `payroll_employees`, `seeding`,
#: `payroll_sync`, `stock_sync`, `single_sync`, `payroll_setup`, `oauth_views`
#: and the xero command. It guarded exactly one caller, `payroll_leave`, which
#: happens to import inside the function: the one nobody had in mind, and none
#: of the ones it was written for. `apps/xero/tests/conftest.py` already said
#: so — "each module imports the function by name, so the source binding is not
#: the one they call" — and every per-module patch in those tests follows it.
#:
#: So Xero is guarded at the SDK's own transport: a method on a class, resolved
#: on the instance at call time, which no import style can pre-bind. Every typed
#: call and the token refresh funnel through it. The raw `requests.post` to
#: identity.xero.com in `auth.py` bypasses the SDK entirely and needs its own
#: entry.
#:
#: The other two are attribute lookups on a module (`litellm.completion`,
#: `geocoding_service.requests`), which a patch does replace.
_VENDOR_ENTRY_POINTS: dict[str, str] = {
    "xero_python.rest.RESTClientObject.request": "Xero",
    "apps.xero.auth.requests": "Xero's token endpoint",
    "litellm.completion": "the LLM gateway",
    "apps.company.services.geocoding_service.requests": "Google Maps",
}


# Opus: docstring rationale unratified (ADR 0051).
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
        # Opus: raising=False: a target is skipped rather than erroring when its
        # module is not importable in this environment, so one optional
        # dependency cannot take the whole suite down.
        monkeypatch.setattr(target, _Refusal(vendor, target), raising=False)


# Opus: docstring rationale unratified (ADR 0051).
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

    # Opus: docstring rationale unratified (ADR 0051).
    def __getattr__(self, name: str) -> object:
        """Hand back another refusal rather than raising here.

        Only CALLING a vendor is the offence. Raising on attribute access
        breaks ``mock.patch``, which reads the attribute to save the original
        before installing a fake — so a test doing the right thing would fail
        at setup with a message telling it to do the thing it was already
        doing.
        """
        return _Refusal(self._vendor, f"{self._target}.{name}")


#: Opus: What an integration test needs from the dev database to talk to a vendor, as
#: (app_label, model, natural key, columns to drop). Resolved through Django's
#: app registry rather than imported, so this file stays outside the layer
#: contract the way its docstring describes.
#:
#: Credentials are migrating out of .env and into the database so they can be
#: changed without a deploy, which means this list GROWS. That is the point of
#: keeping it in one place: a new credential model is one row here, not a new
#: mechanism.
#:
#: Staff is here for the same reason as the credentials, though it is linkage
#: rather than a secret: ``xero_user_id`` names the Xero employee a timesheet
#: posts against, and without it payroll has nothing to post for. That link is
#: also a real production failure mode — a restored database carries another
#: organisation's employee ids until the seed re-links them (#75) — so it is
#: copied from the dev database rather than manufactured, where it is true or
#: broken exactly as production would have it.
_CREDENTIAL_MODELS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("xero", "XeroApp", ("client_id",), ()),
    ("ai", "AIProvider", ("name",), ()),
    ("crm", "PhoneProviderSettings", ("id",), ()),
    # Opus: default_labour_subtype points at a row whose id differs between databases,
    # and no payroll path reads it. The id is dropped too: the test database
    # seeds the automation account itself, so that row must be UPDATED in place
    # rather than have a foreign id forced onto it — which trips the unique
    # constraint on email instead. XeroApp keeps its id, which the active-app
    # lookup and its cache resolve against.
    ("accounts", "Staff", ("email",), ("default_labour_subtype_id", "id")),
    # Opus: The test fixtures seed pay items with PLACEHOLDER xero_ids
    # ("xero-earnings-1.00"). They are truthy, so the posting preflight passes
    # them, and then Xero rejects the timesheet with "The earnings rate is
    # required" because no such rate exists. Copying the real ids over them is
    # what lets a timesheet line name a rate. Matched on (name, uses_leave_api)
    # — the model's own unique key, because "Holiday Pay" is both an earnings
    # rate and a leave type — and the id is dropped so the seeded rows are
    # updated in place, leaving every job's FK pointing where it already did.
    ("xero", "XeroPayItem", ("name", "uses_leave_api"), ("id",)),
)

#: Opus: CompanyDefaults is a singleton the test database already seeds, so it is
#: updated in place rather than inserted. These are the columns that identify
#: the Xero org — without them payroll cannot resolve a calendar.
_COMPANY_DEFAULTS_CREDENTIAL_FIELDS = (
    # Opus: Which Xero org the token is for. Without it every call raises before it
    # reaches the network, so it is as load-bearing as the token itself.
    "xero_tenant_id",
    "xero_shortcode",
    "xero_payroll_calendar_name",
    "xero_payroll_calendar_id",
    "xero_payroll_start_date",
    "accounting_provider",
)


#: Opus: The columns Xero itself mutates. Everything else about a XeroApp row is
#: configuration we own; these five are vendor state, and Xero rotates the
#: refresh token on every refresh — issuing a new one and permanently
#: consuming the old.
_XERO_TOKEN_COLUMNS = ("token_type", "access_token", "refresh_token", "expires_at", "scope")


# Opus: docstring rationale unratified (ADR 0051).
@pytest.fixture
def integration_credentials(db: None) -> "Iterator[None]":  # noqa: ARG001 -- Opus: requesting `db` IS the dependency: it gives this fixture the test database to write into
    """Copy vendor credentials from the dev database into the test database.

    Integration tests call real vendors (ADR 0050), which needs real
    credentials — and those live in the database now, not in .env. Copying them
    into pytest's throwaway database keeps the isolation the test database
    exists for: everything the test does to OUR side rolls back, while the
    vendor side is the test's own to clean up.

    **The Xero token is the one thing copied back.** It is not ours to isolate:
    Xero rotates the refresh token globally on every refresh, so the moment a
    test refreshes, the dev database's copy is dead at the vendor. Letting the
    rollback discard the new one left dev holding a consumed token, and the
    next thing to need a refresh — the next run, the E2E preflight, the hourly
    sync — got ``invalid_grant``. Isolation is the right default for our rows
    and the wrong one for vendor state.

    The write-back runs in this fixture's teardown, which is inside the test's
    transaction and therefore the last moment the rotated value exists.

    Rejected alternative: pointing the test run at the dev database directly.
    It would give the same credentials and also hand every integration test
    write access to real local data, for no gain — the vendor is the thing
    under test, not our rows.
    """
    import psycopg
    from django.apps import apps as django_apps

    source_dsn = _source_connection()

    with psycopg.connect(source_dsn) as source:
        for app_label, model_name, natural_key, dropped in _CREDENTIAL_MODELS:
            _copy_rows(source, django_apps.get_model(app_label, model_name), natural_key, dropped)
        _copy_company_defaults(source, django_apps.get_model("core", "CompanyDefaults"))

    xero_app = django_apps.get_model("xero", "XeroApp")
    copied_token = _active_xero_token(xero_app)

    yield

    _write_back_rotated_token(xero_app, copied_token, source_dsn)


# Opus: docstring rationale unratified (ADR 0051).
def _source_connection() -> str:
    """Build a conninfo string reaching the dev database.

    A conninfo string rather than kwargs because ``psycopg.connect`` also takes
    keyword-only options of its own (``autocommit``, ``row_factory``), so
    splatting a dict of connection parameters into it is untypeable.
    """
    import os

    from django.conf import settings
    from psycopg.conninfo import make_conninfo

    source_name = os.environ["DB_NAME"]
    target = settings.DATABASES["default"]
    if target["NAME"] == source_name:
        raise RuntimeError(
            f"Refusing to copy credentials: the test database IS {source_name}. "
            "Integration tests must run against pytest's own database."
        )
    return make_conninfo(
        dbname=source_name,
        user=str(target["USER"]),
        password=str(target["PASSWORD"]),
        host=str(target["HOST"]),
        port=str(target["PORT"]),
    )


def _active_xero_token(xero_app: "type[Model]") -> "dict[str, Any] | None":
    """The active app's token columns, as the test database currently holds them."""
    return (
        xero_app._default_manager.filter(is_active=True).values("id", *_XERO_TOKEN_COLUMNS).first()
    )


# Opus: docstring rationale unratified (ADR 0051).
def _write_back_rotated_token(
    xero_app: "type[Model]",
    copied_token: "dict[str, Any] | None",
    source_dsn: str,
) -> None:
    """Return a token Xero rotated during the test to the dev database.

    Silent on no-change by design: most tests never trigger a refresh, and a
    write per test would be noise obscuring the one that matters. A failure
    here is NOT swallowed — losing the only live token is how a developer ends
    up hand-driving OAuth, which is the thing this whole path exists to stop.
    """
    import psycopg

    current = _active_xero_token(xero_app)
    if current is None or current == copied_token:
        return

    assignments = ", ".join(f'"{column}" = %({column})s' for column in _XERO_TOKEN_COLUMNS)
    with psycopg.connect(source_dsn) as destination:
        with destination.cursor() as cursor:
            cursor.execute(
                f'UPDATE "{xero_app._meta.db_table}" SET {assignments} WHERE "id" = %(id)s',  # noqa: S608 -- Opus: columns are module constants, values are bound
                current,
            )
        destination.commit()


def _copy_rows(
    source: "Connection[Any]",
    model: "type[Model]",
    natural_key: "tuple[str, ...]",
    dropped: "tuple[str, ...]" = (),
) -> None:
    """Mirror every row of a table into the test database, minus the dropped columns."""
    columns = [
        str(field.column)
        for field in model._meta.concrete_fields
        if str(field.column) not in dropped
    ]
    quoted = ", ".join(f'"{column}"' for column in columns)
    with source.cursor() as cursor:
        cursor.execute(f'SELECT {quoted} FROM "{model._meta.db_table}"')  # noqa: S608 -- Opus: columns come from the model, not input
        rows = cursor.fetchall()
    if not rows:
        raise RuntimeError(
            f"No {model.__name__} rows in the dev database. Integration tests need real "
            "credentials; configure the integration before writing its test (ADR 0050)."
        )
    for row in rows:
        values = dict(zip(columns, row, strict=True))
        lookup = {column: values[column] for column in natural_key}
        model._default_manager.update_or_create(**lookup, defaults=values)


def _copy_company_defaults(source: "Connection[Any]", model: "type[Model]") -> None:
    """Copy the Xero org identifiers onto the seeded CompanyDefaults singleton."""
    quoted = ", ".join(f'"{field}"' for field in _COMPANY_DEFAULTS_CREDENTIAL_FIELDS)
    with source.cursor() as cursor:
        cursor.execute(f'SELECT {quoted} FROM "{model._meta.db_table}" LIMIT 1')  # noqa: S608 -- Opus: fields are module constants
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("The dev database has no CompanyDefaults row to copy Xero config from.")
    # Opus: The seeded singleton, reached through the manager rather than get_solo:
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
        office_email="office@example.test",
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
        office_email="super@example.test",
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
