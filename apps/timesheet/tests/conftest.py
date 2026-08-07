"""Shared fixtures for the timesheet app's service and API tests."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine, CostSet

PASSWORD = "s3cret-Pass!"
# A Monday, so week/day arithmetic in the tests is unambiguous.
WEEK_START = date(2026, 5, 4)
EMPLOYED_SINCE = datetime(2025, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_default_cache() -> None:
    """Isolate cached payroll task ids between tests."""
    cache.clear()


def make_staff(
    email: str,
    *,
    is_office_staff: bool = False,
    is_superuser: bool = False,
    base_wage_rate: Decimal = Decimal("40.00"),
    xero_user_id: str | None = None,
    **extra: object,
) -> Staff:
    """Create a staff member visible to the timesheet surfaces.

    ``get_displayable_staff`` hides anyone without a UUID-shaped
    ``xero_user_id`` (v1: developer/admin logins), so every fixture staff
    member gets one unless the test explicitly wants them hidden.
    """
    staff = Staff.objects.create_user(
        email=email,
        password=PASSWORD,
        first_name=extra.pop("first_name", "Test"),
        last_name=extra.pop("last_name", "Person"),
        is_office_staff=is_office_staff,
        is_superuser=is_superuser,
        base_wage_rate=base_wage_rate,
        xero_user_id=(xero_user_id or None) if xero_user_id is not None else str(uuid.uuid4()),
        **extra,
    )
    # date_joined defaults to now, which would hide the staff member from any
    # date-window filter for a past week.
    Staff.objects.filter(pk=staff.pk).update(date_joined=EMPLOYED_SINCE)
    staff.refresh_from_db()
    return staff


@pytest.fixture
def superuser() -> Staff:
    """A superuser - the only role v1 let manage timesheets.

    No ``xero_user_id``, like the real admin logins, so they stay out of the
    timesheet grids the tests assert on.
    """
    return make_staff(
        "timesheet-super@example.com",
        is_office_staff=True,
        is_superuser=True,
        xero_user_id="",
        first_name="Sam",
        last_name="Super",
    )


@pytest.fixture
def office_staff() -> Staff:
    """Office staff who are NOT superusers (rejected by the management surface)."""
    return make_staff(
        "timesheet-office@example.com",
        is_office_staff=True,
        xero_user_id="",
        first_name="Olive",
        last_name="Office",
    )


@pytest.fixture
def worker() -> Staff:
    """A workshop staff member: base 40.00 + 20% loading = wage_rate 48.00."""
    return make_staff(
        "timesheet-worker@example.com",
        first_name="Wendy",
        last_name="Workshop",
    )


@pytest.fixture
def other_worker() -> Staff:
    """A second workshop staff member, for the ownership tests."""
    return make_staff(
        "timesheet-other@example.com",
        first_name="Otto",
        last_name="Other",
    )


@pytest.fixture
def unpaid_worker() -> Staff:
    """A staff member whose wage rate was never configured (pricing must refuse)."""
    return make_staff(
        "timesheet-unpaid@example.com",
        base_wage_rate=Decimal("0.00"),
        first_name="Unpriced",
        last_name="Person",
    )


@pytest.fixture
def manage_client(superuser: Staff) -> Client:
    """A client authenticated as a superuser (the management surface)."""
    return authenticated_client(superuser)


@pytest.fixture
def worker_client(worker: Staff) -> Client:
    """A client authenticated as a workshop staff member (self-service)."""
    return authenticated_client(worker)


def authenticated_client(staff: Staff) -> Client:
    """A django test client carrying the staff member's access cookie."""
    client = Client()
    authenticate(client, staff)
    return client


@pytest.fixture
def company() -> Company:
    """A company allowed to hold jobs, with the job prerequisites seeded."""
    return make_company("Timesheet Test Company")


@pytest.fixture
def job(company: Company, superuser: Staff) -> Job:
    """A job whose workshop charge-out rate is a round 120.00."""
    job = make_job(company, superuser, name="Timesheet Job")
    job.labour_rates.filter(labour_subtype=LabourSubtype.default_workshop()).update(
        charge_out_rate=Decimal("120.00")
    )
    return job


def make_time_line(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
    job: Job,
    staff: Staff,
    *,
    accounting_date: date,
    hours: str = "8.000",
    unit_cost: str = "48.00",
    unit_rev: str = "120.00",
    cost_set: CostSet | None = None,
    **meta: object,
) -> CostLine:
    """Create an actual time line for a staff member (the shape the UI produces)."""
    pay_item = job.default_xero_pay_item
    line = CostLine(
        cost_set=cost_set if cost_set is not None else job.cost_sets.get(kind="actual"),
        kind="time",
        labour_subtype=LabourSubtype.default_workshop(),
        desc="Timesheet work",
        quantity=Decimal(hours),
        unit_cost=Decimal(unit_cost),
        unit_rev=Decimal(unit_rev),
        accounting_date=accounting_date,
        staff=staff,
        xero_pay_item=pay_item,
        meta={
            "staff_id": str(staff.id),
            "created_from_timesheet": True,
            "is_billable": True,
            "wage_rate_multiplier": 1.0,
            **meta,
        },
    )
    line.save()
    return line
