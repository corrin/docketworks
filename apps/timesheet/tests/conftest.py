"""Shared fixtures for the timesheet app's service and API tests."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.core.cache import caches
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine, CostSet
from apps.timesheet.models import LeaveType, PostingSurface

PASSWORD = "s3cret-Pass!"
# A Monday, so week/day arithmetic in the tests is unambiguous.
WEEK_START = date(2026, 5, 4)
EMPLOYED_SINCE = date(2025, 1, 1)


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Isolate cached payroll runs, progress events and claims between tests.

    Opus: Both aliases, by name. Payroll progress and the posting claim live on
    "shared" (they cross the worker/web boundary in production), and under
    settings_test both aliases are LocMemCache with no LOCATION — which makes
    them one store, so clearing the default happened to clear the other too.
    Naming both stops a leaked claim from failing the next test the day that
    configuration changes.
    """
    for alias in ("default", "shared"):
        caches[alias].clear()


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
    return Staff.objects.create_user(
        office_email=email,
        password=PASSWORD,
        first_name=extra.pop("first_name", "Test"),
        last_name=extra.pop("last_name", "Person"),
        is_office_staff=is_office_staff,
        is_superuser=is_superuser,
        base_wage_rate=base_wage_rate,
        employment_start_date=EMPLOYED_SINCE,
        xero_user_id=(xero_user_id or None) if xero_user_id is not None else str(uuid.uuid4()),
        **extra,
    )


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
    """Create an actual time line for a staff member (the shape the UI produces).

    Opus: A category Xero pays from its own calculation gets NO pay item — the job
    still carries one as a NOT NULL dropdown default, and copying it is the
    write that put public-holiday hours on the Timesheets API on top of Xero's
    own line. ``CostLine.clean`` refuses it, so a fixture that set one would be
    testing a shape the application cannot produce.
    """
    leave_type = LeaveType.objects.filter(job_id=job.id).first()
    pays_itself = (
        leave_type is not None and leave_type.posting_surface is PostingSurface.XERO_COMPUTED
    )
    pay_item = None if pays_itself else job.default_xero_pay_item
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


#: The Docketworks category each seeded Xero leave type belongs to.
LEAVE_CODE_BY_PAY_ITEM = {
    "Sick Leave": LeaveType.Code.SICK,
    "Annual Leave": LeaveType.Code.ANNUAL,
    "Unpaid Leave": LeaveType.Code.UNPAID,
    "Bereavement Leave": LeaveType.Code.BEREAVEMENT,
}


def make_leave_job(company: Company, superuser: Staff, pay_item_name: str) -> Job:
    """A leave job as an onboarded installation has it: pay item AND category.

    Opus: The one implementation. Three test modules each had their own copy, and
    all three bound the pay item WITHOUT the LeaveType that claims it — a state
    no real installation runs, because the seed migration binds the five
    categories as soon as the special jobs exist. The classifier refuses such a
    line, correctly: nothing can say whether an unclaimed Xero leave type is
    paid (ADR 0015, ADR 0039).
    """
    from django.apps import apps as django_apps

    job = make_job(company, superuser, name=pay_item_name)
    job.default_xero_pay_item = django_apps.get_model("xero", "XeroPayItem")._default_manager.get(
        name=pay_item_name, uses_leave_api=True
    )
    job.save(staff=superuser, update_fields=["default_xero_pay_item", "updated_at"])
    LeaveType.objects.filter(code=LEAVE_CODE_BY_PAY_ITEM[pay_item_name]).update(job=job)
    return job


def make_public_holiday_job(company: Company, superuser: Staff) -> Job:
    """The stat-holiday job, whose lines name no Xero object and post nowhere."""
    job = make_job(company, superuser, name="Statutory holiday")
    LeaveType.objects.filter(code=LeaveType.Code.PUBLIC_HOLIDAY).update(job=job)
    return job
