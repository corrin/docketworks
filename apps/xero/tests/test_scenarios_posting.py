"""Approved time reaching Xero payroll: the posting scenarios of the plan (2026-10-25).

One test per scenario in the owner's list, named by its id. Each week is set up
through the timesheet services the screens call, then posted through
``payroll_push.post_payroll_week`` against an in-memory Xero that holds what a
real organisation would: its timesheets, their lines and their status. Every
expected number is worked out by hand in the comments beside it.

Here rather than with the timesheet tests: the layer contract forbids
apps.timesheet importing apps.xero.
"""

import uuid
from datetime import date, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from xero_python.exceptions import ApiException
from xero_python.payrollnz import Timesheet

from apps.accounting.types import StaffWeekPosting, StaffWeekPostResult
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.factories import make_company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import AppError
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.timesheet.services import approval, attendance, workshop_timesheet_service
from apps.timesheet.services.workshop_timesheet_service import WorkshopEntryCreateData
from apps.timesheet.tests.conftest import (
    WEEK_START,
    make_break_job,
    make_leave_job,
    make_staff,
    make_time_line,
)
from apps.xero import payroll_push, payroll_sdk
from apps.xero.constants import PAYROLL_UNIT_PRECISION

pytestmark = pytest.mark.django_db

TENANT = "tenant-1"
MONDAY = WEEK_START
TUESDAY = WEEK_START + timedelta(days=1)
ORDINARY = "xero-earnings-1.00"
TIME_AND_A_HALF = "xero-earnings-1.50"
DOUBLE = "xero-earnings-2.00"

#: A timesheet line as Xero received it: its date, earnings rate and units.
type SentLine = tuple[date | None, str | None, float | None]


class FakeXeroPayroll:
    """One organisation's payroll as Xero holds it, for the calls posting makes.

    Timesheets are kept per employee with their lines and status, so a second
    post meets the first one's timesheet exactly as it would in Xero.
    """

    def __init__(self) -> None:
        self.timesheets: dict[str, payroll_push.PostedTimesheet] = {}
        self.lines: dict[str, list[payroll_push.TimesheetLinePayload]] = {}
        #: Every timesheet created, as its lines were sent.
        self.sent: list[list[SentLine]] = []
        #: Each staff week's leave posting handed to the Leave API: whose, and its hours.
        self.leave: list[tuple[str, list[Decimal]]] = []
        self.calls: list[str] = []
        #: Set to make Xero refuse the next timesheet it is sent.
        self.refusal: ApiException | None = None

    # The PayrollNzApi calls post_timesheet makes.

    def create_timesheet(self, *, xero_tenant_id: str, timesheet: Timesheet) -> SimpleNamespace:
        assert xero_tenant_id == TENANT
        self.calls.append("create")
        if self.refusal is not None:
            raise self.refusal
        timesheet_id = f"ts-{len(self.sent) + 1}"
        lines = timesheet.timesheet_lines or []
        self.sent.append(
            [(line.date, line.earnings_rate_id, line.number_of_units) for line in lines]
        )
        payloads = []
        for line in lines:
            assert line.date is not None
            assert line.earnings_rate_id is not None
            assert line.number_of_units is not None
            payloads.append(
                payroll_push.TimesheetLinePayload(
                    date=line.date,
                    earnings_rate_id=line.earnings_rate_id,
                    units=Decimal(str(line.number_of_units)).quantize(PAYROLL_UNIT_PRECISION),
                )
            )
        self.lines[timesheet_id] = payloads
        employee_id = str(timesheet.employee_id)
        self.timesheets[employee_id] = payroll_push.PostedTimesheet(
            timesheet_id=timesheet_id, employee_id=employee_id, status=payroll_push.STATUS_DRAFT
        )
        # Not the SDK's TimesheetObject: its Timesheet refuses a None calendar id,
        # and Xero's answer is only read for the new timesheet's id.
        return SimpleNamespace(timesheet=SimpleNamespace(timesheet_id=timesheet_id))

    def approve_timesheet(self, *, xero_tenant_id: str, timesheet_id: str) -> None:
        assert xero_tenant_id == TENANT
        self.calls.append(f"approve:{timesheet_id}")
        self._set_status(timesheet_id, payroll_push.STATUS_APPROVED)

    def revert_timesheet(self, *, xero_tenant_id: str, timesheet_id: str) -> None:
        assert xero_tenant_id == TENANT
        self.calls.append(f"revert:{timesheet_id}")
        self._set_status(timesheet_id, payroll_push.STATUS_DRAFT)

    def delete_timesheet(self, *, xero_tenant_id: str, timesheet_id: str) -> None:
        assert xero_tenant_id == TENANT
        self.calls.append(f"delete:{timesheet_id}")
        self.timesheets = {
            employee: held
            for employee, held in self.timesheets.items()
            if held.timesheet_id != timesheet_id
        }

    def _set_status(self, timesheet_id: str, status: str) -> None:
        [(employee, _held)] = [
            (employee, held)
            for employee, held in self.timesheets.items()
            if held.timesheet_id == timesheet_id
        ]
        self.timesheets[employee] = payroll_push.PostedTimesheet(
            timesheet_id=timesheet_id, employee_id=employee, status=status
        )

    # The module-level reads and the leave write payroll_push makes.

    def existing(self, _week: object, *, tenant_id: str) -> dict[str, payroll_push.PostedTimesheet]:
        assert tenant_id == TENANT
        return dict(self.timesheets)

    def timesheet_lines(
        self, timesheet_id: str, *, tenant_id: str
    ) -> list[payroll_push.TimesheetLinePayload]:
        assert tenant_id == TENANT
        return list(self.lines[timesheet_id])

    def reconcile_leave(
        self,
        _employee_id: UUID,
        lines: list[CostLine],
        _week: object,
        *,
        tenant_id: str,
        staff_name: str,
    ) -> None:
        assert tenant_id == TENANT
        self.leave.append((staff_name, [line.quantity for line in lines]))


@pytest.fixture
def xero(monkeypatch: pytest.MonkeyPatch) -> FakeXeroPayroll:
    """Point every Xero call posting makes at one in-memory organisation."""
    fake = FakeXeroPayroll()
    calendar = uuid.uuid4()
    monkeypatch.setattr(payroll_sdk, "connected_tenant", lambda: TENANT)
    monkeypatch.setattr(payroll_sdk, "payroll_api", lambda: fake)
    monkeypatch.setattr(payroll_push, "refresh_pay_runs", lambda **_kwargs: None)
    monkeypatch.setattr(payroll_push, "ensure_pay_run_for_week", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(payroll_push, "existing_timesheets_for_week", fake.existing)
    monkeypatch.setattr(payroll_push, "timesheet_lines", fake.timesheet_lines)
    monkeypatch.setattr(payroll_push, "reconcile_leave_for_staff_week", fake.reconcile_leave)
    monkeypatch.setattr(
        payroll_push, "posted_leave_hours", lambda *_args, **_kwargs: Decimal("0.000")
    )
    monkeypatch.setattr(payroll_push, "_calendar_id", lambda: calendar)
    monkeypatch.setattr("apps.xero.payroll_push.time.sleep", lambda _seconds: None)
    return fake


@pytest.fixture
def superuser() -> Staff:
    return make_staff(
        "posting-super@example.com", is_office_staff=True, is_superuser=True, xero_user_id=""
    )


@pytest.fixture
def office() -> Staff:
    return make_staff(
        "posting-office@example.com",
        is_office_staff=True,
        xero_user_id="",
        first_name="Olive",
        last_name="Office",
    )


@pytest.fixture
def worker() -> Staff:
    """Wage 48.00: base 40.00 plus the 20% loading."""
    return make_staff("posting-worker@example.com", first_name="Wendy", last_name="Workshop")


@pytest.fixture
def company() -> Company:
    return make_company("Posting Scenarios Company")


@pytest.fixture
def job(company: Company, superuser: Staff) -> Job:
    """A customer job charging 120.00 an hour."""
    job = make_job(company, superuser, name="Posting Job")
    job.labour_rates.filter(labour_subtype=LabourSubtype.default_workshop()).update(
        charge_out_rate=Decimal("120.00")
    )
    return job


@pytest.fixture(autouse=True)
def _break_job(superuser: Staff) -> Job:
    return make_break_job(superuser)


def _enter(  # noqa: PLR0913 -- an entry as the drawer saves it: who, whose, where, how long, when, at what rate
    actor: Staff,
    owner: Staff,
    job: Job,
    hours: str,
    *,
    day: date = MONDAY,
    rate: str = "1.0",
) -> None:
    """Save an entry given hours alone, as the drawer does when no start is typed."""
    data: WorkshopEntryCreateData = {
        "job_id": job.id,
        "accounting_date": day,
        "hours": Decimal(hours),
        "wage_rate_multiplier": Decimal(rate),
    }
    workshop_timesheet_service.create_entry(actor, owner, data)


def _post(*staff: Staff) -> list[StaffWeekPostResult]:
    return list(payroll_push.post_payroll_week(TENANT, [each.id for each in staff], MONDAY))


def _status(worker: Staff) -> StaffWeekPosting:
    [row] = [
        row
        for row in payroll_push.week_posting_status(MONDAY, tenant_id=TENANT)
        if row.staff_id == str(worker.id)
    ]
    return row


def test_t1_ordinary_overtime_and_double_time_post_as_three_earnings_lines(
    xero: FakeXeroPayroll, office: Staff, worker: Staff, job: Job
) -> None:
    """Ordinary, 1.5x and 2x lines on one day post as three earnings-rate lines for that date.

    Guards payroll_push._timesheet_line_payloads.
    """
    _enter(worker, worker, job, "4")
    _enter(worker, worker, job, "2", rate="1.5")
    _enter(worker, worker, job, "1", rate="2.0")
    approval.approve_day(worker, MONDAY, office)

    [result] = _post(worker)

    assert result.success
    [sent] = xero.sent
    assert sorted(sent, key=str) == [
        (MONDAY, ORDINARY, 4.0),
        (MONDAY, TIME_AND_A_HALF, 2.0),
        (MONDAY, DOUBLE, 1.0),
    ]


def test_t2_xeros_refusal_of_an_overtime_line_is_recorded_and_nothing_changes(
    xero: FakeXeroPayroll, office: Staff, worker: Staff, job: Job
) -> None:
    """He has an overtime line, but his Xero pay template has no overtime earnings rate.

    Xero refuses. Docketworks records Xero's message, changes nothing, and
    stops (the Xero disparity rule).

    Guards payroll_push._post_one_staff_week.
    """
    _enter(worker, worker, job, "2", rate="1.5")
    approval.approve_day(worker, MONDAY, office)
    xero.refusal = ApiException(
        status=400, reason="Earnings rate Time and one half is not on the employee's pay template"
    )
    refusal = str(xero.refusal)
    [before] = CostLine.objects.filter(cost_set__job=job, staff=worker)

    [result] = _post(worker)

    assert (result.success, result.error) == (False, refusal)
    assert AppError.objects.filter(message=refusal).count() == 1
    assert xero.calls == ["create"], "nothing is approved or retried after Xero refuses"
    [after] = CostLine.objects.filter(cost_set__job=job, staff=worker)
    assert (after.quantity, after.approved, after.unit_cost, after.xero_pay_item_id) == (
        before.quantity,
        before.approved,
        before.unit_cost,
        before.xero_pay_item_id,
    )


def test_t3_lunch_and_unpaid_leave_are_never_on_the_timesheet(  # noqa: PLR0913, PLR0917 -- pytest fixtures: each is a party to the scenario
    xero: FakeXeroPayroll,
    office: Staff,
    superuser: Staff,
    worker: Staff,
    job: Job,
    company: Company,
) -> None:
    """Unpaid lunch and unpaid leave are never posted.

    Guards payroll_push._week_time_lines (UNPAID_TIME) and _split_by_surface.
    """
    # 07:00-15:00 puts two paid quarter-hour breaks and the unpaid lunch on Monday.
    attendance.set_clock_times(worker, MONDAY, time(7), time(15), worker)
    _enter(worker, worker, job, "7")
    approval.approve_day(worker, MONDAY, office)
    unpaid_leave = make_leave_job(company, superuser, "Unpaid Leave")
    # Tuesday's unpaid leave, booked on the Leave screen.
    leave = make_time_line(unpaid_leave, worker, accounting_date=TUESDAY, hours="8.000")
    CostLine.objects.filter(pk=leave.pk).update(managed_by="leave")

    _post(worker)

    # Monday: 7h on the job + 0.25h + 0.25h paid breaks = 7.5h; lunch is not hours.
    [sent] = xero.sent
    assert sent == [(MONDAY, ORDINARY, 7.5)]


def test_j1_only_approved_time_is_posted_per_day_and_rate_with_leave_on_its_own(  # noqa: PLR0913, PLR0917 -- pytest fixtures: each is a party to the scenario
    xero: FakeXeroPayroll,
    office: Staff,
    superuser: Staff,
    worker: Staff,
    job: Job,
    company: Company,
) -> None:
    """Only approved time goes to Xero, per day per earnings rate: ordinary, 1.5x, 2x, leave.

    Unpaid time is never posted.

    Guards payroll_push._week_time_lines, _split_by_surface and _timesheet_line_payloads.
    """
    _enter(worker, worker, job, "3")
    _enter(worker, worker, job, "1", rate="1.5")
    approval.approve_day(worker, MONDAY, office)
    _enter(worker, worker, job, "2", day=TUESDAY, rate="2.0")
    approval.approve_day(worker, TUESDAY, office)
    # Waiting on Tuesday: never approved, so never paid.
    _enter(worker, worker, job, "5", day=TUESDAY)
    # Wednesday's 4h of annual leave, booked on the Leave screen.
    annual = make_leave_job(company, superuser, "Annual Leave")
    leave = make_time_line(
        annual, worker, accounting_date=WEEK_START + timedelta(days=2), hours="4.000"
    )
    CostLine.objects.filter(pk=leave.pk).update(managed_by="leave")

    _post(worker)

    [sent] = xero.sent
    assert sorted(sent, key=str) == [
        (MONDAY, ORDINARY, 3.0),
        (MONDAY, TIME_AND_A_HALF, 1.0),
        (TUESDAY, DOUBLE, 2.0),
    ]
    assert xero.leave == [("Wendy Workshop", [Decimal("4.000")])]


def test_c5_a_late_entry_approved_after_posting_waits_for_the_re_post_which_replaces_the_week(
    xero: FakeXeroPayroll, office: Staff, worker: Staff, job: Job
) -> None:
    """The week was posted to Xero, then the office approves a late entry.

    Held back until the week is posted again. The re-post replaces the week in Xero.

    Guards payroll_push.post_timesheet.
    """
    _enter(worker, worker, job, "4")
    approval.approve_day(worker, MONDAY, office)
    _post(worker)
    _enter(worker, worker, job, "2", day=TUESDAY)

    approval.approve_day(worker, TUESDAY, office)

    assert xero.calls == ["create", "approve:ts-1"], "approving posted nothing to Xero"
    assert xero.lines["ts-1"] == [
        payroll_push.TimesheetLinePayload(MONDAY, ORDINARY, Decimal("4.000"))
    ]

    _post(worker)

    # The approved ts-1 is reverted and deleted, and the week sent whole as ts-2.
    assert xero.calls[2:] == ["revert:ts-1", "delete:ts-1", "create", "approve:ts-2"]
    assert sorted(xero.sent[1], key=str) == [(MONDAY, ORDINARY, 4.0), (TUESDAY, ORDINARY, 2.0)]


@pytest.mark.usefixtures("xero")
def test_s5_an_office_edit_after_posting_shows_as_a_mismatch_until_re_posted(
    office: Staff, worker: Staff, job: Job
) -> None:
    """The office edits an approved entry after the week was posted, and approves it again.

    The edit takes the approval off (owner, 2026-10-26: entering and approving
    are two operations). Approved again, the week no longer matches Xero, and
    reconciliation shows it until the week is re-posted.

    Guards payroll_push.week_posting_status.
    """
    _enter(worker, worker, job, "4")
    approval.approve_day(worker, MONDAY, office)
    _post(worker)
    assert _status(worker).matches
    [line] = CostLine.objects.filter(cost_set__job=job, staff=worker)

    workshop_timesheet_service.update_entry(office, {"entry_id": line.id, "hours": Decimal("3")})
    approval.approve_day(worker, MONDAY, office)

    edited = _status(worker)
    assert (edited.recorded_timesheet_hours, edited.posted_timesheet_hours) == (
        Decimal("3.000"),
        Decimal("4.000"),
    )
    assert not edited.matches

    _post(worker)

    assert _status(worker).matches


def test_n6_a_person_with_no_xero_employee_is_refused_by_name_and_his_time_kept(
    xero: FakeXeroPayroll, office: Staff, job: Job
) -> None:
    """A person with no Xero employee link.

    Posting refuses his week and names him. His entries are untouched.

    Guards payroll_push._post_one_staff_week.
    """
    unlinked = make_staff(
        "posting-unlinked@example.com", xero_user_id="", first_name="Nora", last_name="Nolink"
    )
    _enter(unlinked, unlinked, job, "6")
    approval.approve_day(unlinked, MONDAY, office)

    [result] = _post(unlinked)

    assert (result.success, result.error) == (
        False,
        (
            "Nora Nolink is not linked to a Xero employee. "
            "Ask an administrator to link them, then post again."
        ),
    )
    assert xero.calls == []
    [line] = CostLine.objects.filter(cost_set__job=job, staff=unlinked)
    assert (line.quantity, line.approved) == (Decimal("6.000"), True)
