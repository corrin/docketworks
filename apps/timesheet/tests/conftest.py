"""Shared fixtures for the timesheet app's service and API tests."""

import uuid
from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol, cast

import pytest
from django.apps import apps as django_apps
from django.core.cache import caches
from django.test import Client
from django.utils import timezone

from apps.accounting.types import (
    PayrollMirrorScope,
    PayRunSyncResult,
    StaffWeekPosting,
    StaffWeekPostResult,
)
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


class PayRunRow(Protocol):
    """The XeroPayRun columns payroll tests read back.

    Fable: A Protocol rather than the model: the layer contract forbids
    ``apps.timesheet -> apps.xero`` imports, so ``make_pay_run`` reaches the
    model through the app registry and this names the fields it hands back.
    """

    pk: uuid.UUID
    xero_id: uuid.UUID
    payroll_calendar_id: uuid.UUID | None


def make_pay_run(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
    tenant: str = "tenant-1",
    *,
    week_start: date = WEEK_START,
    end: date | None = None,
    payment: date | None = None,
    calendar_id: uuid.UUID | None = None,
    status: str = "Draft",
) -> PayRunRow:
    """A mirrored Xero pay run covering the week beginning ``week_start``.

    The one row builder for the mirror table (ADR 0039). ``end`` defaults to
    the week's Sunday and ``payment`` to ``end``; tests whose subject buckets
    by payment date pass it explicitly.
    """
    period_end = end if end is not None else week_start + timedelta(days=6)
    return cast(
        "PayRunRow",
        django_apps.get_model("xero", "XeroPayRun")._default_manager.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id=tenant,
            payroll_calendar_id=calendar_id,
            period_start_date=week_start,
            period_end_date=period_end,
            payment_date=payment if payment is not None else period_end,
            pay_run_status=status,
            pay_run_type="Scheduled",
            raw_json={},
            xero_last_modified=timezone.now(),
        ),
    )


def make_week_posting(  # noqa: PLR0913 -- fixture builder exposes each compared payroll value
    *,
    posted: bool,
    staff_id: str = "staff-1",
    posted_timesheet: str = "0",
    posted_leave: str = "0",
    recorded_timesheet: str = "0",
    recorded_leave: str = "0",
    pay_basis: str | None = None,
) -> StaffWeekPosting:
    """One staff row of the week-posting comparison, both sides split by surface."""
    return StaffWeekPosting(
        staff_id=staff_id,
        posted=posted,
        timesheet_status="Approved" if posted else None,
        posted_timesheet_hours=Decimal(posted_timesheet),
        posted_leave_hours=Decimal(posted_leave),
        recorded_timesheet_hours=Decimal(recorded_timesheet),
        recorded_leave_hours=Decimal(recorded_leave),
        pay_basis=pay_basis,
    )


class FakePayrollProvider:
    """The accounting provider's payroll surface: known answers, every call recorded.

    Fable: One fake for every suite that injects a payroll provider (ADR 0039)
    — the pay-run API tests assert the wire mapping over its fixed answers,
    and the posting-task tests assert dispatch, progress and claim handling
    over the results/error it is constructed with. Employee CRUD
    (list/create/rename) is NOT here: that protocol slice is disjoint and has
    its own recording fake in test_payroll_employee_sync.
    """

    provider_name = "Fake"
    supports_payroll = True

    def __init__(
        self,
        results: Sequence[StaffWeekPostResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        #: None means "one generic success per staff id"; a sequence is yielded as given.
        self.results = results
        self.error = error
        self.calls: list[tuple[str, Sequence[uuid.UUID], date]] = []
        self.mirror_calls: list[tuple[str, PayrollMirrorScope]] = []
        self.refresh_calls = 0
        #: Set per test; what week_posting_status answers.
        self.week_status: list[StaffWeekPosting] = []

    def payroll_connection_id(self) -> str:
        return "tenant-1"

    def sync_payroll_mirror(self, connection_id: str, scope: PayrollMirrorScope) -> None:
        self.mirror_calls.append((connection_id, scope))

    def payroll_calendar_anchor_week(self) -> tuple[date, date] | None:
        return None

    def refresh_pay_runs(self) -> PayRunSyncResult:
        self.refresh_calls += 1
        return PayRunSyncResult(fetched=0, created=0, updated=0)

    def post_payroll_week(
        self,
        connection_id: str,
        staff_ids: Sequence[uuid.UUID],
        week_start_date: date,
    ) -> Iterator[StaffWeekPostResult]:
        self.calls.append((connection_id, staff_ids, week_start_date))
        if self.error is not None:
            raise self.error
        if self.results is not None:
            yield from self.results
            return
        for staff_id in staff_ids:
            yield StaffWeekPostResult(
                staff_id=str(staff_id), staff_name="Wendy Workshop", success=True
            )

    @property
    def posted_weeks(self) -> list[date]:
        """The weeks a posting run reached the provider for, in call order."""
        return [week for _connection, _staff_ids, week in self.calls]

    def week_posting_status(
        self,
        week_start_date: date,  # noqa: ARG002 -- Opus: part of the provider signature; this fake answers for a fixed week
    ) -> list[StaffWeekPosting]:
        return list(self.week_status)


#: The Docketworks category each seeded Xero leave type belongs to.
LEAVE_CODE_BY_PAY_ITEM = {
    "Sick Leave": LeaveType.Code.SICK,
    "Annual Leave": LeaveType.Code.ANNUAL,
    "Unpaid Leave": LeaveType.Code.UNPAID,
    "Bereavement Leave": LeaveType.Code.BEREAVEMENT,
}


def make_leave_job(company: Company, superuser: Staff, pay_item_name: str) -> Job:
    """A leave job as an onboarded installation has it: special, with pay item AND category.

    Opus: The one implementation; every test module reaches a configured
    Leave-API category through this. All the copies it replaced bound the pay
    item WITHOUT the LeaveType that claims it — a state no real installation
    runs, because the seed migration binds the five categories as soon as the
    special jobs exist. The classifier refuses such a line, correctly: nothing
    can say whether an unclaimed Xero leave type is paid (ADR 0015, ADR 0039).

    Fable: Each step mirrors the production door (ADR 0052): a special-status
    job as ``create_shop_jobs`` writes it, then the seeded pay item bound and
    the LeaveType converged exactly as
    ``apps.xero.leave_configuration.configure_default_leave_types`` does.
    Tests needing the category row itself read ``LeaveType.objects.get(code=…)``
    rather than this returning two objects.
    """
    from django.apps import apps as django_apps

    job = make_job(company, superuser, name=pay_item_name, status="special")
    job.default_xero_pay_item = django_apps.get_model("xero", "XeroPayItem")._default_manager.get(
        name=pay_item_name, uses_leave_api=True
    )
    job.save(staff=superuser, update_fields=["default_xero_pay_item", "updated_at"])
    LeaveType.objects.update_or_create(
        code=LEAVE_CODE_BY_PAY_ITEM[pay_item_name],
        defaults={"display_name": pay_item_name, "job": job},
    )
    return job


def make_public_holiday_job(company: Company, superuser: Staff) -> Job:
    """The stat-holiday job, whose lines name no Xero object and post nowhere.

    Fable: Special status and no pay-item binding, as
    ``configure_default_leave_types`` leaves it: the job keeps its NOT NULL
    "Ordinary Time" dropdown default, which classifies nothing because the
    catalogue indexes pay items for Leave-API categories only.
    """
    job = make_job(company, superuser, name="Statutory holiday", status="special")
    LeaveType.objects.update_or_create(code=LeaveType.Code.PUBLIC_HOLIDAY, defaults={"job": job})
    return job
