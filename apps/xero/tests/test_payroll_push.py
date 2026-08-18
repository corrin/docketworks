"""The payroll push's decisions, isolated from Xero.

These cover the rules that are easy to get subtly wrong and expensive to
discover afterwards: how lines are routed between Xero's two payroll APIs, how
leave runs are shaped, and when a re-post is a no-op. The Xero calls themselves
are the E2E spec's job against the demo company.
"""
# Opus: docstring rationale unratified (ADR 0051).

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.utils import timezone
from xero_python.payrollnz import TimesheetLine

from apps.accounting.types import NotAPayrollWeekError
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.tests.conftest import WEEK_START, make_staff, make_time_line
from apps.xero import payroll_leave, payroll_push
from apps.xero.models import XeroPayRun

pytestmark = pytest.mark.django_db


# Opus: The staff/company/job factories live with the timesheet fixtures; these wire
# them up locally rather than growing a second set of the same concept.


@pytest.fixture
def payroll_superuser() -> Staff:
    return make_staff("payroll-push-super@example.com", is_superuser=True, xero_user_id="")


@pytest.fixture
def company() -> Company:
    from apps.company.tests.conftest import make_company  # noqa: PLC0415

    return make_company("Payroll Push Test Company")


@pytest.fixture
def superuser(payroll_superuser: Staff) -> Staff:
    return payroll_superuser


@pytest.fixture
def worker() -> Staff:
    return make_staff("payroll-push-worker@example.com")


@pytest.fixture
def job(company: Company, superuser: Staff) -> Job:
    return make_job(company, superuser, name="Payroll Push Job")


def _leave_job(company: Company, superuser: Staff, pay_item_name: str) -> Job:
    """A job carrying a leave pay item, the shape leave bookings take."""
    from django.apps import apps as django_apps  # noqa: PLC0415

    job = make_job(company, superuser, name=pay_item_name)
    job.default_xero_pay_item = django_apps.get_model("xero", "XeroPayItem")._default_manager.get(
        name=pay_item_name, uses_leave_api=True
    )
    job.save(staff=superuser, update_fields=["default_xero_pay_item", "updated_at"])
    return job


def _lines(job: Job) -> list[CostLine]:
    return list(
        CostLine.objects.filter(
            cost_set__job=job, cost_set__kind="actual", kind="time"
        ).select_related("xero_pay_item")
    )


class TestWeekWindow:
    def test_a_week_runs_monday_to_sunday(self) -> None:
        week = payroll_push._WeekWindow.of(WEEK_START)

        assert week.start == date(2026, 5, 4)
        assert week.end == date(2026, 5, 10)

    def test_any_other_start_day_is_refused(self) -> None:
        """Xero pay periods are anchored on Mondays; a Tuesday would post to the wrong period."""
        with pytest.raises(NotAPayrollWeekError, match="must be a Monday"):
            payroll_push._WeekWindow.of(date(2026, 5, 5))


class TestRouting:
    def test_leave_and_work_go_to_different_xero_apis(
        self, company: Company, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        """Only the Leave API debits a leave balance, so the split is not cosmetic."""
        sick = _leave_job(company, superuser, "Sick Leave")
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(sick, worker, accounting_date=WEEK_START, hours="4.000")

        leave_lines, timesheet_lines = payroll_push._split_by_api(_lines(job) + _lines(sick))

        assert [line.quantity for line in leave_lines] == [Decimal("4.000")]
        assert [line.quantity for line in timesheet_lines] == [Decimal("8.000")]

    def test_lines_are_aggregated_per_day_and_earnings_rate(self, job: Job, worker: Staff) -> None:
        """Xero takes one line per (date, rate); sending three would triple the hours."""
        for _ in range(3):
            make_time_line(job, worker, accounting_date=WEEK_START, hours="2.500")

        payloads = payroll_push._timesheet_line_payloads(_lines(job))

        assert len(payloads) == 1
        assert payloads[0].date == WEEK_START
        assert payloads[0].units == Decimal("7.500")

    # Opus: docstring rationale unratified (ADR 0051).
    def test_hours_are_aggregated_exactly_not_in_binary_floating_point(
        self, job: Job, worker: Staff
    ) -> None:
        """Three tenths of an hour, three times, is nine tenths — not 0.8999999999999999.

        These are the hours a person is paid for, so the sum is held in the
        Decimal the column already stores and never routed through float.
        """
        for _ in range(3):
            make_time_line(job, worker, accounting_date=WEEK_START, hours="0.300")

        [payload] = payroll_push._timesheet_line_payloads(_lines(job))

        assert payload.units == Decimal("0.900")
        assert str(payload.units) == "0.900"


class TestSalaryPosting:
    def test_salary_hours_stay_local_and_an_existing_timesheet_is_removed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        worker: Staff,
        job: Job,
    ) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        worker.pay_basis = "salary"
        worker.save(update_fields=["pay_basis", "updated_at"])
        employee_id = str(worker.xero_user_id)
        existing = payroll_push.PostedTimesheet(
            timesheet_id="salary-ts-1",
            employee_id=employee_id,
            status=payroll_push.STATUS_DRAFT,
        )
        api = MagicMock()
        delete_timesheet = MagicMock()
        monkeypatch.setattr(payroll_push, "_payroll_api", lambda: api)
        monkeypatch.setattr(payroll_push, "_tenant", lambda: "tenant-1")
        monkeypatch.setattr(payroll_push, "_delete_timesheet", delete_timesheet)

        result = payroll_push._post_one_staff_week(
            worker,
            _lines(job),
            payroll_push._WeekWindow.of(WEEK_START),
            {employee_id: existing},
        )

        assert result.success
        assert result.skipped
        assert result.posting_mode == "salary"
        assert result.salary_timesheet_removed
        assert result.work_hours == Decimal("8.000")
        delete_timesheet.assert_called_once_with(api, "tenant-1", existing)
        api.create_timesheet.assert_not_called()


def _payload(units: str) -> payroll_push.TimesheetLinePayload:
    return payroll_push.TimesheetLinePayload(
        date=WEEK_START, earnings_rate_id="rate-1", units=Decimal(units)
    )


# Opus: docstring rationale unratified (ADR 0051).
class TestRepostIsANoOp:
    """Whether an unchanged re-post skips the delete-and-recreate.

    Both sides are the same payload type now. They used not to be: the
    comparison took SDK objects read back from Xero, whose line dates come back
    null from BOTH the list and the detail endpoint — so it never matched, and
    every re-post deleted and recreated. Hand-built objects here carried dates,
    which is why these tests passed throughout. Only the live API shows it, so
    the round trip is asserted in test_payroll_integration.py.
    """

    def test_matching_lines_are_recognised(self) -> None:
        assert payroll_push._lines_match([_payload("8.000")], [_payload("8.000")]) is True

    def test_changed_hours_are_not_matching(self) -> None:
        assert payroll_push._lines_match([_payload("8.000")], [_payload("7.500")]) is False

    def test_order_does_not_matter(self) -> None:
        """Xero returns lines in its own order; a week is the SET of its lines."""
        monday = _payload("8.000")
        tuesday = payroll_push.TimesheetLinePayload(
            date=WEEK_START + timedelta(days=1),
            earnings_rate_id="rate-1",
            units=Decimal("4.000"),
        )

        assert payroll_push._lines_match([monday, tuesday], [tuesday, monday]) is True

    # Opus: docstring rationale unratified (ADR 0051).
    def test_a_duplicated_line_in_xero_is_not_a_match(self) -> None:
        """Set equality made [line, line] equal [line], leaving payable hours behind.

        We never create duplicates — the payload is aggregated per (date,
        rate) — but Xero is edited by people too, and reporting "already
        correct" is the one answer that writes nothing to fix it.
        """
        line = _payload("8.000")

        assert payroll_push._lines_match([line, line], [line]) is False


class TestLeaveRequests:
    def test_consecutive_days_become_one_request_carrying_the_total(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """Xero keeps only the period total, so per-day requests would lose the shape."""
        annual = _leave_job(company, superuser, "Annual Leave")
        for offset, hours in enumerate(("8.000", "8.000", "4.500")):
            make_time_line(
                annual, worker, accounting_date=WEEK_START + timedelta(days=offset), hours=hours
            )

        [spec] = payroll_leave._build_leave_requests(_lines(annual))

        assert spec["start_date"] == WEEK_START
        assert spec["end_date"] == WEEK_START + timedelta(days=2)
        assert spec["total_units"] == Decimal("20.500")

    def test_a_gap_splits_the_run_in_two(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        annual = _leave_job(company, superuser, "Annual Leave")
        make_time_line(annual, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(
            annual, worker, accounting_date=WEEK_START + timedelta(days=3), hours="8.000"
        )

        specs = sorted(
            payroll_leave._build_leave_requests(_lines(annual)), key=lambda s: s["start_date"]
        )

        assert [spec["start_date"] for spec in specs] == [
            WEEK_START,
            WEEK_START + timedelta(days=3),
        ]

    def test_different_leave_types_never_merge(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        sick = _leave_job(company, superuser, "Sick Leave")
        annual = _leave_job(company, superuser, "Annual Leave")
        make_time_line(sick, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(
            annual, worker, accounting_date=WEEK_START + timedelta(days=1), hours="8.000"
        )

        specs = payroll_leave._build_leave_requests(_lines(sick) + _lines(annual))

        assert len({spec["leave_type_id"] for spec in specs}) == 2

    def test_the_payload_carries_one_period_spanning_the_payroll_week(self) -> None:
        """Verified live (KAN-326): per-day periods have their units discarded by Xero."""
        week = payroll_push._WeekWindow.of(WEEK_START)
        spec = payroll_leave.LeaveRequestSpec(
            leave_type_id="leave-1",
            start_date=WEEK_START,
            end_date=WEEK_START + timedelta(days=2),
            total_units=Decimal("20.5"),
            description="Annual Leave",
        )

        payload = payroll_leave._leave_payload(spec, week)

        assert payload.periods is not None
        [period] = payload.periods
        assert period.period_start_date == week.start
        assert period.period_end_date == week.end
        assert period.number_of_units == pytest.approx(20.5)

    def test_leave_outside_the_payroll_week_is_refused(self) -> None:
        week = payroll_push._WeekWindow.of(WEEK_START)
        spec = payroll_leave.LeaveRequestSpec(
            leave_type_id="leave-1",
            start_date=WEEK_START - timedelta(days=1),
            end_date=WEEK_START,
            total_units=Decimal("8"),
            description="Annual Leave",
        )

        with pytest.raises(ValueError, match="outside the payroll week"):
            payroll_leave._leave_payload(spec, week)


class TestDraftPayRunBlock:
    def test_xeros_string_only_refusal_is_recognised(self) -> None:
        """Xero gives no code for this, so the message is the only signal."""
        exc = Exception(
            "Could not delete the leave request. There is a draft pay run for this employee."
        )

        assert payroll_leave._is_draft_pay_run_leave_block(exc) is True

    def test_an_unrelated_failure_is_not_mistaken_for_it(self) -> None:
        assert (
            payroll_leave._is_draft_pay_run_leave_block(Exception("Rate limit exceeded")) is False
        )


# Opus: docstring rationale unratified (ADR 0051).
class TestMatchingTimesheetMustBeApproved:
    """A timesheet holding the right hours is not necessarily a posted one.

    `create_timesheet` and `approve_timesheet` are two calls. If the first
    succeeds and the second fails, Xero keeps a Draft carrying exactly the
    hours we wanted — and the operator's retry finds them matching. Returning
    early on the strength of the lines alone reported a clean success for a
    timesheet nobody had approved.
    """

    def _api(self, monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
        """Stub the surface post_timesheet touches, recording what it calls."""
        monkeypatch.setattr(payroll_push, "_tenant", lambda: "tenant")
        monkeypatch.setattr(
            payroll_push, "timesheet_lines", lambda _timesheet_id: [_payload("8.000")]
        )
        monkeypatch.setattr("apps.xero.payroll_push.time.sleep", lambda _seconds: None)

        class _Api:
            def approve_timesheet(self, **kwargs: str) -> None:
                calls.append(f"approve:{kwargs['timesheet_id']}")

            def delete_timesheet(self, **_kwargs: str) -> None:
                calls.append("delete")

            def revert_timesheet(self, **_kwargs: str) -> None:
                calls.append("revert")

        monkeypatch.setattr(payroll_push, "_payroll_api", _Api)

    def test_a_matching_approved_timesheet_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        self._api(monkeypatch, calls)
        existing = payroll_push.PostedTimesheet(
            timesheet_id="ts-1", employee_id="emp-1", status=payroll_push.STATUS_APPROVED
        )

        result = payroll_push.post_timesheet(
            uuid.uuid4(), payroll_push._WeekWindow.of(WEEK_START), [_payload("8.000")], existing
        )

        assert result is existing
        assert calls == []

    def test_a_matching_draft_is_approved_rather_than_reported_as_posted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression: this used to return the Draft and report success."""
        calls: list[str] = []
        self._api(monkeypatch, calls)
        existing = payroll_push.PostedTimesheet(
            timesheet_id="ts-1", employee_id="emp-1", status=payroll_push.STATUS_DRAFT
        )

        result = payroll_push.post_timesheet(
            uuid.uuid4(), payroll_push._WeekWindow.of(WEEK_START), [_payload("8.000")], existing
        )

        assert calls == ["approve:ts-1"], "a matching Draft must be approved, not accepted"
        assert result.status == payroll_push.STATUS_APPROVED
        # Opus: Not deleted and recreated: the hours are already right, and a
        # delete/create pair costs four rate-limited calls to reach the same place.
        assert "delete" not in calls


# Opus: docstring rationale unratified (ADR 0051).
@pytest.mark.django_db
class TestStaffListIsValidatedBeforeAnyWrite:
    """An unresolvable or repeated staff id must not reach Xero at all.

    The check used to sit in the final loop, after leave reconciliation and
    pay-run creation had already written — and because this is a generator
    consumed one result at a time, everyone ahead of the bad id had their
    timesheet deleted, recreated and approved first. The docstring claimed the
    opposite ("fails whole rather than half-posted"), which was true of every
    input except the one it was written for.
    """

    def _record_writes(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Trip a marker on every call that would reach Xero."""
        writes: list[str] = []

        def _record(name: str, result: object = None) -> "Callable[..., object]":
            def _call(*_args: object, **_kwargs: object) -> object:
                writes.append(name)
                return result

            return _call

        monkeypatch.setattr(payroll_push, "reconcile_leave_for_staff_week", _record("leave"))
        monkeypatch.setattr(payroll_push, "ensure_pay_run_for_week", _record("pay_run"))
        monkeypatch.setattr(payroll_push, "existing_timesheets_for_week", _record("list", {}))
        monkeypatch.setattr(payroll_push, "_post_one_staff_week", _record("post"))
        return writes

    def test_an_unknown_staff_id_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job
    ) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        writes = self._record_writes(monkeypatch)

        with pytest.raises(ValueError, match="not found"):
            list(payroll_push.post_payroll_week([worker.id, uuid.uuid4()], WEEK_START))

        assert writes == [], "payroll was written before the staff list was validated"

    def test_a_repeated_staff_id_is_posted_once(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job
    ) -> None:
        """Both loops iterated the argument, so a repeat reconciled and posted twice."""
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        writes = self._record_writes(monkeypatch)

        list(payroll_push.post_payroll_week([worker.id, worker.id], WEEK_START))

        assert writes.count("post") == 1
        assert writes.count("leave") == 1


# Opus: docstring rationale unratified (ADR 0051).
class TestPostedLeaveHours:
    """The leave half of the read-back, which no timesheet can show.

    `payroll_push._posted_total` sees the Timesheets API only, so without this
    a week containing leave reported a shortfall equal to the leave.
    """

    def _leave(self, start: date | None, end: date | None, units: str) -> SimpleNamespace:
        return SimpleNamespace(
            leave_id="leave-1",
            start_date=start,
            end_date=end,
            periods=[SimpleNamespace(period_start_date=start, number_of_units=float(units))],
        )

    def _stub(self, monkeypatch: pytest.MonkeyPatch, leaves: list[SimpleNamespace]) -> None:
        monkeypatch.setattr(payroll_leave, "_tenant", lambda: "tenant")

        class _Api:
            def get_employee_leaves(self, **_kwargs: str) -> SimpleNamespace:
                return SimpleNamespace(leave=leaves)

        monkeypatch.setattr(payroll_leave, "_payroll_api", _Api)

    def test_leave_inside_the_week_is_totalled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        week = payroll_push._WeekWindow.of(WEEK_START)
        self._stub(
            monkeypatch,
            [
                self._leave(WEEK_START, WEEK_START + timedelta(days=1), "8"),
                self._leave(WEEK_START + timedelta(days=2), WEEK_START + timedelta(days=2), "4"),
            ],
        )

        assert payroll_leave.posted_leave_hours(uuid.uuid4(), week) == Decimal("12.000")

    # Opus: docstring rationale unratified (ADR 0051).
    def test_leave_spanning_the_week_boundary_belongs_to_neither_week(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same containment rule the reconcile uses, so the two cannot disagree.

        Xero keeps one period per pay period, and a request straddling the
        boundary is not this week's to count — splitting it here would double
        it across two weeks.
        """
        week = payroll_push._WeekWindow.of(WEEK_START)
        self._stub(monkeypatch, [self._leave(WEEK_START - timedelta(days=1), WEEK_START, "8")])

        assert payroll_leave.posted_leave_hours(uuid.uuid4(), week) == Decimal("0.000")

    def test_an_unreadable_date_range_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Guessing which week undated leave belongs to would move someone's pay."""
        week = payroll_push._WeekWindow.of(WEEK_START)
        self._stub(monkeypatch, [self._leave(None, None, "8")])

        with pytest.raises(ValueError, match="unreadable date range"):
            payroll_leave.posted_leave_hours(uuid.uuid4(), week)


# Opus: docstring rationale unratified (ADR 0051).
@pytest.mark.django_db
class TestWeekPostingStatus:
    """What Xero holds for a week, beside what the timesheet recorded.

    Both sides are carried and each is split timesheet vs leave, because the
    two reach Xero through different APIs and only leave debits a balance —
    comparing a combined total against the timesheet side alone reported a
    shortfall on every week containing leave.
    """

    def _stub_xero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        timesheets: dict[str, payroll_push.PostedTimesheet],
        posted_units: str = "0",
        leave_units: str = "0",
    ) -> None:
        monkeypatch.setattr(payroll_push, "existing_timesheets_for_week", lambda _week: timesheets)
        monkeypatch.setattr(payroll_push, "timesheet_lines", lambda _id: [_payload(posted_units)])
        monkeypatch.setattr(
            payroll_push, "posted_leave_hours", lambda _employee, _week: Decimal(leave_units)
        )

    def test_it_reports_both_sides_for_a_posted_week(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job
    ) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        employee_id = str(worker.xero_user_id)
        self._stub_xero(
            monkeypatch,
            timesheets={
                employee_id: payroll_push.PostedTimesheet(
                    timesheet_id="ts-1",
                    employee_id=employee_id,
                    status=payroll_push.STATUS_APPROVED,
                )
            },
            posted_units="8.000",
        )

        [status] = [
            row
            for row in payroll_push.week_posting_status(WEEK_START)
            if row.staff_id == str(worker.id)
        ]

        assert status.posted is True
        assert status.posted_timesheet_hours == Decimal("8.000")
        assert status.recorded_timesheet_hours == Decimal("8.000")
        assert status.matches

    def test_a_staff_member_xero_holds_nothing_for_is_not_a_match(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job
    ) -> None:
        """Recorded hours with no timesheet is the underpaying half of the pair."""
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        self._stub_xero(monkeypatch, timesheets={})

        [status] = [
            row
            for row in payroll_push.week_posting_status(WEEK_START)
            if row.staff_id == str(worker.id)
        ]

        assert status.posted is False
        assert status.recorded_timesheet_hours == Decimal("8.000")
        assert not status.matches

    def test_leave_is_counted_on_its_own_surface(
        self, monkeypatch: pytest.MonkeyPatch, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """Leave never appears on a timesheet, so a combined total misreads it."""
        leave_job = _leave_job(company, superuser, "Annual Leave")
        make_time_line(leave_job, worker, accounting_date=WEEK_START, hours="8.000")
        employee_id = str(worker.xero_user_id)
        self._stub_xero(
            monkeypatch,
            timesheets={
                employee_id: payroll_push.PostedTimesheet(
                    timesheet_id="ts-1",
                    employee_id=employee_id,
                    status=payroll_push.STATUS_APPROVED,
                )
            },
            leave_units="8.000",
        )

        [status] = [
            row
            for row in payroll_push.week_posting_status(WEEK_START)
            if row.staff_id == str(worker.id)
        ]

        assert status.recorded_leave_hours == Decimal("8.000")
        assert status.recorded_timesheet_hours == Decimal("0")
        assert status.posted_leave_hours == Decimal("8.000")
        assert status.matches

    # Opus: docstring rationale unratified (ADR 0051).
    def test_someone_who_left_before_the_week_is_not_reported(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """The same filter the weekly grid uses, so the two cannot disagree.

        This read used to roll its own — every row with a non-empty
        xero_user_id, no employment window — so it answered for people the grid
        never showed, and those rows could be matched against nothing.
        """
        worker.date_left = WEEK_START - timedelta(days=1)
        worker.save(update_fields=["date_left"])
        self._stub_xero(monkeypatch, timesheets={})

        reported = [row.staff_id for row in payroll_push.week_posting_status(WEEK_START)]

        assert str(worker.id) not in reported


class TestUndatedLinesAreRefused:
    """A null line date means the timesheet was deleted, not that a line is spare.

    v1 recorded the cause: Xero returns nulls for date, earnings rate and units
    after a delete. Skipping those lines understated the hours Xero holds, which
    reads as a mismatch, which deletes and recreates a timesheet that was
    already correct — churn on the money path, driven by data we chose to hide.
    """

    def _dated(self, units: str = "8.0") -> TimesheetLine:
        return TimesheetLine(
            date=WEEK_START, earnings_rate_id="rate-1", number_of_units=float(units)
        )

    def _stub(self, monkeypatch: pytest.MonkeyPatch, lines: list[TimesheetLine]) -> None:
        monkeypatch.setattr(payroll_push, "_tenant", lambda: "tenant")
        response = SimpleNamespace(timesheet=SimpleNamespace(timesheet_lines=lines))

        class _Api:
            def get_timesheet(self, **_kwargs: object) -> SimpleNamespace:
                return response

        monkeypatch.setattr(payroll_push, "_payroll_api", _Api)

    def test_dated_lines_read_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub(monkeypatch, [self._dated()])

        [line] = payroll_push.timesheet_lines("ts-1")

        assert line.units == Decimal("8.000")

    def test_an_undated_line_is_refused_rather_than_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression: this used to return 8h and silently drop the rest."""
        undated = TimesheetLine(date=None, earnings_rate_id=None, number_of_units=None)
        self._stub(monkeypatch, [self._dated(), undated])

        with pytest.raises(ValueError, match="DELETED"):
            payroll_push.timesheet_lines("ts-1")


# Opus: docstring rationale unratified (ADR 0051).
@pytest.mark.django_db
class TestLeaveFailureAbortsTheBatch:
    """v1 stops before creating a pay run or posting timesheets on leave failure."""

    def test_failure_escapes_and_no_timesheets_are_posted(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job
    ) -> None:
        other = make_staff("payroll-push-other@example.com")
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(job, other, accounting_date=WEEK_START, hours="4.000")

        def _reconcile(employee_id: uuid.UUID, *_args: object, **_kwargs: object) -> None:
            if str(employee_id) == str(worker.xero_user_id):
                raise RuntimeError("Xero refused the leave request")

        monkeypatch.setattr(payroll_push, "reconcile_leave_for_staff_week", _reconcile)
        pay_run_calls: list[object] = []
        monkeypatch.setattr(
            payroll_push, "ensure_pay_run_for_week", lambda *_a: pay_run_calls.append(object())
        )
        monkeypatch.setattr(
            payroll_push,
            "_post_one_staff_week",
            lambda *_a: pytest.fail("timesheets must not post after leave reconciliation fails"),
        )

        with pytest.raises(RuntimeError, match="Xero refused"):
            list(payroll_push.post_payroll_week([worker.id, other.id], WEEK_START))

        assert pay_run_calls == []


class TestPayRunTenantIsolation:
    def _run(self, tenant: str, *, status: str = "Draft") -> XeroPayRun:
        run_id = uuid.uuid4()
        return XeroPayRun.objects.create(
            xero_id=run_id,
            xero_tenant_id=tenant,
            payroll_calendar_id=uuid.uuid4(),
            period_start_date=WEEK_START,
            period_end_date=WEEK_START + timedelta(days=6),
            payment_date=WEEK_START + timedelta(days=9),
            pay_run_status=status,
            pay_run_type="Scheduled",
            raw_json={},
            xero_last_modified=timezone.now(),
        )

    def test_refresh_deletes_only_orphans_for_the_connected_tenant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ours = self._run("ours")
        foreign = self._run("foreign")
        monkeypatch.setattr(payroll_push, "_tenant", lambda: "ours")
        monkeypatch.setattr(
            payroll_push,
            "get_pay_runs_for_sync",
            lambda: SimpleNamespace(pay_runs=[]),
        )

        payroll_push.refresh_pay_runs()

        assert not XeroPayRun.objects.filter(pk=ours.pk).exists()
        assert XeroPayRun.objects.filter(pk=foreign.pk).exists()

    def test_a_foreign_draft_does_not_block_this_tenant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        foreign = self._run("foreign")
        monkeypatch.setattr(payroll_push, "_tenant", lambda: "ours")
        monkeypatch.setattr(payroll_push, "_calendar_id", lambda: foreign.payroll_calendar_id)
        created = SimpleNamespace(pay_run_id="new-run")
        monkeypatch.setattr(payroll_push, "create_pay_run", lambda _week: created)

        assert payroll_push.ensure_pay_run_for_week(WEEK_START).pay_run_id == "new-run"

    def test_create_refetches_the_pay_run_before_mirroring(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calendar_id = str(uuid.uuid4())
        pay_run_id = str(uuid.uuid4())
        CompanyDefaults.objects.filter(id=1).update(xero_payroll_calendar_name="Weekly")
        calendar = SimpleNamespace(id=calendar_id, name="Weekly")
        created = SimpleNamespace(
            pay_run_id=pay_run_id,
            period_start_date=WEEK_START,
            period_end_date=WEEK_START + timedelta(days=6),
        )
        detail = SimpleNamespace(pay_run_id=pay_run_id)
        api = SimpleNamespace(
            create_pay_run=lambda **_kwargs: SimpleNamespace(pay_run=created),
            get_pay_run=lambda **_kwargs: SimpleNamespace(pay_run=detail),
        )
        mirrored = SimpleNamespace(
            payroll_calendar_id=calendar_id,
            period_start_date=WEEK_START,
            period_end_date=WEEK_START + timedelta(days=6),
            payment_date=WEEK_START + timedelta(days=9),
            pay_run_status="Draft",
            pay_run_type="Scheduled",
        )
        transformed: list[object] = []

        def _transform(value: object, _xero_id: str) -> tuple[object, str]:
            transformed.append(value)
            return mirrored, "created"

        monkeypatch.setattr(payroll_push, "_tenant", lambda: "ours")
        monkeypatch.setattr(payroll_push, "_payroll_api", lambda: api)
        monkeypatch.setattr(payroll_push, "get_payroll_calendars", lambda: [calendar])
        monkeypatch.setattr(payroll_push, "transform_pay_run", _transform)

        result = payroll_push.create_pay_run(WEEK_START)

        assert transformed == [detail]
        assert result.pay_run_id == pay_run_id


class TestLeaveUpdateResponse:
    def test_update_returns_the_id_xero_confirmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = MagicMock()
        api.update_employee_leave.return_value = SimpleNamespace(
            leave=SimpleNamespace(leave_id="confirmed-leave")
        )
        session = payroll_leave._LeaveSession(
            api=api,
            tenant_id="tenant",
            employee_id=uuid.uuid4(),
            week=payroll_push._WeekWindow.of(WEEK_START),
        )
        existing = SimpleNamespace(leave_id="old-leave")
        spec: payroll_leave.LeaveRequestSpec = {
            "leave_type_id": "annual",
            "start_date": WEEK_START,
            "end_date": WEEK_START,
            "total_units": Decimal("8.000"),
            "description": "Annual Leave",
        }
        monkeypatch.setattr("apps.xero.payroll_leave.time.sleep", lambda _seconds: None)

        leave_id = payroll_leave._update_leave(session, existing, spec, WEEK_START, WEEK_START)

        assert leave_id == "confirmed-leave"

    def test_update_refuses_an_empty_xero_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = MagicMock()
        api.update_employee_leave.return_value = None
        session = payroll_leave._LeaveSession(
            api=api,
            tenant_id="tenant",
            employee_id=uuid.uuid4(),
            week=payroll_push._WeekWindow.of(WEEK_START),
        )
        existing = SimpleNamespace(leave_id="old-leave")
        spec: payroll_leave.LeaveRequestSpec = {
            "leave_type_id": "annual",
            "start_date": WEEK_START,
            "end_date": WEEK_START,
            "total_units": Decimal("8.000"),
            "description": "Annual Leave",
        }
        monkeypatch.setattr("apps.xero.payroll_leave.time.sleep", lambda _seconds: None)

        with pytest.raises(ValueError, match="returned no leave record"):
            payroll_leave._update_leave(session, existing, spec, WEEK_START, WEEK_START)
