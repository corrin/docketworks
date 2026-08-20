"""The payroll push's decisions, isolated from Xero.

Opus: These cover the rules that are easy to get subtly wrong and expensive to
discover afterwards: how lines are routed between Xero's two payroll APIs, how
leave runs are shaped, and when a re-post is a no-op. The Xero calls themselves
are the E2E spec's job against the demo company.
"""

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from xero_python.payrollnz import EmployeeLeave, TimesheetLine

from apps.accounting.types import NotAPayrollWeekError
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.services import hour_categories
from apps.timesheet.tests.conftest import (
    WEEK_START,
    make_leave_job,
    make_pay_run,
    make_public_holiday_job,
    make_staff,
    make_time_line,
)
from apps.xero import payroll_leave, payroll_push, payroll_sdk
from apps.xero.models import XeroPayRun

#: Opus: The organisation a posting run is dispatched for. post_payroll_week refuses
#: any other connected tenant (ADR 0024), so the tests that drive it patch
#: ``payroll_sdk.connected_tenant`` to this and pass it as the dispatched id.
POSTING_TENANT = "tenant-1"

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


@pytest.fixture
def xero_writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every posting call that would reach Xero, in the order it was reached.

    Opus: A list rather than a mock per call site, because what these tests assert
    is ORDER and COUNT across the whole run — that nothing was written before a
    refusal, and that a repeated staff id posts once. Patched at the module
    boundary ``post_payroll_week`` calls through, so a call added inside one of
    these functions still lands under the marker its caller trips.
    """
    writes: list[str] = []

    def _record(name: str, result: object = None) -> "Callable[..., object]":
        def _call(*_args: object, **_kwargs: object) -> object:
            writes.append(name)
            return result

        return _call

    monkeypatch.setattr(payroll_sdk, "connected_tenant", lambda: POSTING_TENANT)
    # Opus: Recorded rather than silenced. The pre-post mirror refresh is one Xero
    # read and the preflight's correctness rests on it, so a test that hid it
    # could not tell "refreshed, then refused" from "refused on whatever the
    # mirror happened to hold".
    monkeypatch.setattr(payroll_push, "refresh_pay_runs", _record("refresh"))
    monkeypatch.setattr(payroll_push, "reconcile_leave_for_staff_week", _record("leave"))
    monkeypatch.setattr(payroll_push, "ensure_pay_run_for_week", _record("pay_run"))
    monkeypatch.setattr(payroll_push, "existing_timesheets_for_week", _record("list", {}))
    monkeypatch.setattr(payroll_push, "_post_one_staff_week", _record("post"))
    return writes


def _catalogue() -> "hour_categories.LeaveCatalogue":
    """The configured categories, as every posting path loads them."""
    return hour_categories.LeaveCatalogue.load()


def _restore_v1_row_without_pay_item(line: CostLine) -> None:
    """Null a work line's pay item the way a v1 database restore delivers it: as a raw row.

    Fable: ``CostLine.clean`` refuses to save a postable time line without a
    pay item, so no supported write path produces this state — but pg_restore
    writes rows, not model saves, and restored v1 data still carries them.
    The queryset update models that arrival. This stays within ADR 0052's
    fixture allowance because the code under test is the preflight VALIDATION
    of such rows, not the write path the update bypasses.
    """
    CostLine.objects.filter(id=line.id).update(xero_pay_item=None)


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
    def test_a_public_holiday_is_posted_to_neither_xero_surface(
        self, company: Company, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        """Xero pays a public holiday from its own calculation, so posting one pays it twice.

        Opus: Measured against the connected organisation: its pay slips carry
        ``Public Holiday (…)`` earnings lines nobody posted, at the Ordinary
        Time rate, with units from the employee's working pattern. Docketworks
        had the category bound to that same rate, so the hours went to the
        Timesheets API on top — and the SDK offers no endpoint to create, amend
        or suppress Xero's own line, which is what makes "post nothing" the only
        correct answer rather than a simplification.
        """
        stat = make_public_holiday_job(company, superuser)
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        # Fable: make_time_line already writes the holiday line with no pay
        # item, the only shape CostLine.clean accepts for this category.
        make_time_line(stat, worker, accounting_date=WEEK_START, hours="8.000")

        split = payroll_push._split_by_surface(_lines(job) + _lines(stat), _catalogue())

        assert [line.quantity for line in split.xero_computed] == [Decimal("8.000")]
        assert [line.quantity for line in split.timesheet] == [Decimal("8.000")]
        assert split.leave_api == [], "a public holiday must not debit a Xero leave balance"

    def test_the_preflight_accepts_a_week_whose_public_holiday_names_no_pay_item(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """The check covers what will be sent; a line that is never sent needs no Xero id."""
        stat = make_public_holiday_job(company, superuser)
        make_time_line(stat, worker, accounting_date=WEEK_START, hours="8.000")

        payroll_push.validate_pay_items_for_week([worker.id], WEEK_START)

    def test_the_preflight_still_refuses_a_postable_line_with_no_pay_item(
        self, worker: Staff, job: Job
    ) -> None:
        """Scoping the check must not blunt it for the lines it exists to guard."""
        line = make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        _restore_v1_row_without_pay_item(line)

        with pytest.raises(ValueError, match=r"no xero_pay_item|not a leave category"):
            payroll_push.validate_pay_items_for_week([worker.id], WEEK_START)

    def test_the_reported_split_and_the_posted_split_agree_line_for_line(
        self, company: Company, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        """The screens and the payroll push must bucket the SAME lines the same way.

        Opus: Asserting ``timesheet + leave_api + xero_computed == total`` proves
        nothing — ``timesheet`` is DEFINED as the remainder, so that identity
        holds however the lines were classified. What can actually break is the
        two consumers disagreeing, which is the drift ADR 0039 exists to stop,
        so this compares the hour split against the line split the push sends.
        """
        stat = make_public_holiday_job(company, superuser)
        sick = make_leave_job(company, superuser, "Sick Leave")
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(sick, worker, accounting_date=WEEK_START, hours="4.000")
        make_time_line(stat, worker, accounting_date=WEEK_START, hours="8.000")

        lines = _lines(job) + _lines(sick) + _lines(stat)
        catalogue = hour_categories.LeaveCatalogue.load()
        categories = hour_categories.categorise(lines, catalogue)
        split = payroll_push._split_by_surface(lines, catalogue)

        def hours(group: list[CostLine]) -> Decimal:
            return sum((line.quantity for line in group), Decimal("0"))

        assert categories.total == Decimal("20.000")
        assert categories.timesheet == hours(split.timesheet)
        assert categories.leave_api == hours(split.leave_api)
        assert categories.xero_computed == hours(split.xero_computed)

    def test_leave_and_work_go_to_different_xero_apis(
        self, company: Company, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        """Only the Leave API debits a leave balance, so the split is not cosmetic."""
        sick = make_leave_job(company, superuser, "Sick Leave")
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(sick, worker, accounting_date=WEEK_START, hours="4.000")

        split = payroll_push._split_by_surface(_lines(job) + _lines(sick), _catalogue())

        assert [line.quantity for line in split.leave_api] == [Decimal("4.000")]
        assert [line.quantity for line in split.timesheet] == [Decimal("8.000")]
        assert split.xero_computed == []

    def test_lines_are_aggregated_per_day_and_earnings_rate(self, job: Job, worker: Staff) -> None:
        """Xero takes one line per (date, rate); sending three would triple the hours."""
        for _ in range(3):
            make_time_line(job, worker, accounting_date=WEEK_START, hours="2.500")

        payloads = payroll_push._timesheet_line_payloads(_lines(job))

        assert len(payloads) == 1
        assert payloads[0].date == WEEK_START
        assert payloads[0].units == Decimal("7.500")

    def test_hours_are_aggregated_exactly_not_in_binary_floating_point(
        self, job: Job, worker: Staff
    ) -> None:
        """Three tenths of an hour, three times, is nine tenths — not 0.8999999999999999.

        Opus: These are the hours a person is paid for, so the sum is held in the
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
        monkeypatch.setattr(payroll_sdk, "payroll_api", lambda: api)
        monkeypatch.setattr(payroll_push, "_delete_timesheet", delete_timesheet)

        result = payroll_push._post_one_staff_week(
            worker,
            _lines(job),
            payroll_push._WeekWindow.of(WEEK_START),
            {employee_id: existing},
            _catalogue(),
            tenant_id="tenant-1",
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


class TestRepostIsANoOp:
    """Whether an unchanged re-post skips the delete-and-recreate.

    Opus: Both sides are the same payload type now. They used not to be: the
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

    def test_a_duplicated_line_in_xero_is_not_a_match(self) -> None:
        """Set equality made [line, line] equal [line], leaving payable hours behind.

        Opus: We never create duplicates — the payload is aggregated per (date,
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
        annual = make_leave_job(company, superuser, "Annual Leave")
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
        annual = make_leave_job(company, superuser, "Annual Leave")
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
        sick = make_leave_job(company, superuser, "Sick Leave")
        annual = make_leave_job(company, superuser, "Annual Leave")
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

    def test_another_weeks_draft_is_refused_without_calling_xero(
        self, xero_writes: list[str], worker: Staff, job: Job
    ) -> None:
        """The requirement is the cost, not the refusal (ADR 0052).

        Opus: The task already refused a blocked week before this preflight
        existed — from Xero's own error, after one ``get_employee_leaves`` per
        staff member. So the message is identical on both sides of the fix and
        asserting it would prove nothing; the call count is the only thing that
        moved. Measured 2026-08-20 against the demo tenant: six attempts at
        ~144 calls each, 862 of a 1,000-call day, to rediscover one draft the
        local mirror already named.
        """
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_pay_run(POSTING_TENANT, week_start=WEEK_START - timedelta(days=7))

        with pytest.raises(ValueError, match="Xero allows only one"):
            list(payroll_push.post_payroll_week(POSTING_TENANT, [worker.id], WEEK_START))

        assert xero_writes == ["refresh"], (
            "the refusal cost more than the one pay-run read it takes to be sure"
        )

    def test_a_draft_xero_holds_blocks_even_when_the_mirror_is_empty(
        self, monkeypatch: pytest.MonkeyPatch, xero_writes: list[str], worker: Staff, job: Job
    ) -> None:
        """The mirror is not the authority; the refresh that precedes it is.

        Opus: This is the state a restored database is in — the mirror comes back
        without the pay runs Xero still holds — and it is the state the E2E
        suite posts from. The check reads the mirror, so it is only as good as
        the refresh in front of it; before that refresh moved into this
        function, the only caller doing it was the Celery task, and posting
        from anywhere else walked into the per-staff loop to be told by Xero.
        """
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")

        def _refresh_finds_a_draft(**_kwargs: object) -> None:
            xero_writes.append("refresh")
            make_pay_run(POSTING_TENANT, week_start=WEEK_START - timedelta(days=7))

        monkeypatch.setattr(payroll_push, "refresh_pay_runs", _refresh_finds_a_draft)

        with pytest.raises(ValueError, match="Xero allows only one"):
            list(payroll_push.post_payroll_week(POSTING_TENANT, [worker.id], WEEK_START))

        assert xero_writes == ["refresh"]

    def test_a_draft_only_the_stale_mirror_believes_in_does_not_block(
        self, monkeypatch: pytest.MonkeyPatch, xero_writes: list[str], worker: Staff, job: Job
    ) -> None:
        """The converse, and the one an operator meets: they cleared it in Xero."""
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        gone = make_pay_run(POSTING_TENANT, week_start=WEEK_START - timedelta(days=7))

        def _refresh_drops_it(**_kwargs: object) -> None:
            xero_writes.append("refresh")
            XeroPayRun.objects.filter(pk=gone.pk).delete()

        monkeypatch.setattr(payroll_push, "refresh_pay_runs", _refresh_drops_it)

        list(payroll_push.post_payroll_week(POSTING_TENANT, [worker.id], WEEK_START))

        assert xero_writes.count("post") == 1

    def test_this_weeks_own_draft_does_not_block_it(
        self, xero_writes: list[str], worker: Staff, job: Job
    ) -> None:
        """Re-posting a week reuses its own draft; only ANOTHER week's blocks."""
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_pay_run(POSTING_TENANT)

        list(payroll_push.post_payroll_week(POSTING_TENANT, [worker.id], WEEK_START))

        assert xero_writes.count("post") == 1


class TestMatchingTimesheetMustBeApproved:
    """A timesheet holding the right hours is not necessarily a posted one.

    Opus: `create_timesheet` and `approve_timesheet` are two calls. If the first
    succeeds and the second fails, Xero keeps a Draft carrying exactly the
    hours we wanted — and the operator's retry finds them matching. Returning
    early on the strength of the lines alone reported a clean success for a
    timesheet nobody had approved.
    """

    def _api(self, monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
        """Stub the surface post_timesheet touches, recording what it calls."""
        monkeypatch.setattr(
            payroll_push,
            "timesheet_lines",
            lambda _timesheet_id, **_kwargs: [_payload("8.000")],
        )
        monkeypatch.setattr("apps.xero.payroll_push.time.sleep", lambda _seconds: None)

        class _Api:
            def approve_timesheet(self, **kwargs: str) -> None:
                calls.append(f"approve:{kwargs['timesheet_id']}")

            def delete_timesheet(self, **_kwargs: str) -> None:
                calls.append("delete")

            def revert_timesheet(self, **_kwargs: str) -> None:
                calls.append("revert")

        monkeypatch.setattr(payroll_sdk, "payroll_api", _Api)

    def test_a_matching_approved_timesheet_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        self._api(monkeypatch, calls)
        existing = payroll_push.PostedTimesheet(
            timesheet_id="ts-1", employee_id="emp-1", status=payroll_push.STATUS_APPROVED
        )

        result = payroll_push.post_timesheet(
            uuid.uuid4(),
            payroll_push._WeekWindow.of(WEEK_START),
            [_payload("8.000")],
            existing,
            tenant_id="tenant",
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
            uuid.uuid4(),
            payroll_push._WeekWindow.of(WEEK_START),
            [_payload("8.000")],
            existing,
            tenant_id="tenant",
        )

        assert calls == ["approve:ts-1"], "a matching Draft must be approved, not accepted"
        assert result.status == payroll_push.STATUS_APPROVED
        # Opus: Not deleted and recreated: the hours are already right, and a
        # delete/create pair costs four rate-limited calls to reach the same place.
        assert "delete" not in calls


@pytest.mark.django_db
class TestStaffListIsValidatedBeforeAnyWrite:
    """An unresolvable or repeated staff id must not reach Xero at all.

    Opus: The check used to sit in the final loop, after leave reconciliation and
    pay-run creation had already written — and because this is a generator
    consumed one result at a time, everyone ahead of the bad id had their
    timesheet deleted, recreated and approved first. The docstring claimed the
    opposite ("fails whole rather than half-posted"), which was true of every
    input except the one it was written for.
    """

    def test_an_unknown_staff_id_writes_nothing(
        self, xero_writes: list[str], worker: Staff, job: Job
    ) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")

        with pytest.raises(ValueError, match="not found"):
            list(
                payroll_push.post_payroll_week(
                    POSTING_TENANT, [worker.id, uuid.uuid4()], WEEK_START
                )
            )

        assert xero_writes == [], (
            "an unknown staff id is answerable from the database and cost a Xero call"
        )

    def test_a_changed_organisation_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, xero_writes: list[str], worker: Staff, job: Job
    ) -> None:
        """A week posted into another organisation's payroll is not recoverable.

        Opus: ADR 0024 has the task carry the tenant it was dispatched for. The
        connected tenant is cached across processes and invalidated by an
        organisation swap, which restore-prod-to-nonprod performs — so a worker
        can pick up a run dispatched for one organisation and resolve another.
        """
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        monkeypatch.setattr(payroll_sdk, "connected_tenant", lambda: "another-organisation")

        with pytest.raises(payroll_push.WrongPayrollTenantError, match=POSTING_TENANT):
            list(payroll_push.post_payroll_week(POSTING_TENANT, [worker.id], WEEK_START))

        assert xero_writes == [], "payroll was written into an organisation it was not meant for"

    def test_a_repeated_staff_id_is_posted_once(
        self, xero_writes: list[str], worker: Staff, job: Job
    ) -> None:
        """Both loops iterated the argument, so a repeat reconciled and posted twice."""
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")

        list(payroll_push.post_payroll_week(POSTING_TENANT, [worker.id, worker.id], WEEK_START))

        assert xero_writes.count("post") == 1
        assert xero_writes.count("leave") == 1


@pytest.mark.django_db
class TestDispatchedTenantIsThreadedThroughTheRun:
    """A tenant swap AFTER the dispatch check must not move a single call.

    Fable: ``constants.tenant_cache`` documents that a worker can resolve the
    PREVIOUS organisation for up to five minutes after a swap.
    ``require_dispatched_tenant`` pins only the run's first moment; what pins
    the rest is that every downstream call carries the verified id as an
    argument instead of re-resolving the singleton. So this drives the REAL
    posting pipeline — reconcile, pay run, timesheet — against a recording
    fake, flips what the singleton answers the moment the check has passed,
    and requires every ``xero_tenant_id`` the fake saw to be the dispatched
    one. The xero_writes fixture cannot prove this: it replaces the very
    functions whose resolution is in question.
    """

    def test_a_mid_run_swap_cannot_redirect_any_call(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job
    ) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        calendar_id = uuid.uuid4()
        CompanyDefaults.objects.filter(id=1).update(
            xero_payroll_calendar_id=calendar_id,
            xero_payroll_calendar_name="Weekly",
        )

        # The dispatch check gets the dispatched organisation; every resolution
        # after it gets the swapped one, exactly as a stale cache entry expiring
        # mid-run would answer.
        answers = iter([POSTING_TENANT])
        monkeypatch.setattr(payroll_sdk, "connected_tenant", lambda: next(answers, "tenant-B"))

        recorded: list[tuple[str, str]] = []

        class _Api:
            def _note(self, method: str, kwargs: dict[str, object]) -> None:
                recorded.append((method, str(kwargs["xero_tenant_id"])))

            def get_employee_leaves(self, **kwargs: object) -> SimpleNamespace:
                self._note("get_employee_leaves", kwargs)
                return SimpleNamespace(leave=[])

            def get_timesheets(self, **kwargs: object) -> SimpleNamespace:
                self._note("get_timesheets", kwargs)
                return SimpleNamespace(timesheets=[])

            def create_pay_run(self, **kwargs: object) -> SimpleNamespace:
                self._note("create_pay_run", kwargs)
                return SimpleNamespace(
                    pay_run=SimpleNamespace(
                        pay_run_id="run-1",
                        period_start_date=WEEK_START,
                        period_end_date=WEEK_START + timedelta(days=6),
                    )
                )

            def get_pay_run(self, **kwargs: object) -> SimpleNamespace:
                self._note("get_pay_run", kwargs)
                return SimpleNamespace(pay_run=SimpleNamespace(pay_run_id="run-1"))

            def create_timesheet(self, **kwargs: object) -> SimpleNamespace:
                self._note("create_timesheet", kwargs)
                return SimpleNamespace(timesheet=SimpleNamespace(timesheet_id="ts-1"))

            def approve_timesheet(self, **kwargs: object) -> None:
                self._note("approve_timesheet", kwargs)

        monkeypatch.setattr(payroll_sdk, "payroll_api", _Api)

        def _pay_runs_for_sync(**kwargs: object) -> SimpleNamespace:
            recorded.append(("get_pay_runs_for_sync", str(kwargs["xero_tenant_id"])))
            return SimpleNamespace(pay_runs=[])

        monkeypatch.setattr(payroll_push, "get_pay_runs_for_sync", _pay_runs_for_sync)
        monkeypatch.setattr(
            payroll_push,
            "get_payroll_calendars",
            lambda **_kwargs: [SimpleNamespace(id=str(calendar_id), name="Weekly")],
        )
        mirrored = SimpleNamespace(
            payroll_calendar_id=calendar_id,
            period_start_date=WEEK_START,
            period_end_date=WEEK_START + timedelta(days=6),
            payment_date=WEEK_START + timedelta(days=9),
            pay_run_status="Draft",
            pay_run_type="Scheduled",
        )
        monkeypatch.setattr(
            payroll_push,
            "transform_pay_run",
            lambda _pay_run, _xero_id, **_kwargs: (mirrored, "created"),
        )
        monkeypatch.setattr("apps.xero.payroll_push.time.sleep", lambda _seconds: None)
        monkeypatch.setattr("apps.xero.payroll_leave.time.sleep", lambda _seconds: None)

        [result] = list(payroll_push.post_payroll_week(POSTING_TENANT, [worker.id], WEEK_START))

        assert result.success, result.error
        assert payroll_sdk.connected_tenant() == "tenant-B", "the swap never became live"
        # The run must have actually crossed every surface, or the property is
        # vacuously true of a run that made no calls.
        methods = {method for method, _tenant in recorded}
        assert {
            "get_pay_runs_for_sync",
            "get_employee_leaves",
            "create_pay_run",
            "get_timesheets",
            "create_timesheet",
            "approve_timesheet",
        } <= methods
        wrong = [(method, tenant) for method, tenant in recorded if tenant != POSTING_TENANT]
        assert wrong == [], f"calls followed the swapped organisation: {wrong}"


class TestPostedLeaveHours:
    """The leave half of the read-back, which no timesheet can show.

    Opus: `payroll_push._posted_total` sees the Timesheets API only, so without this
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
        class _Api:
            def get_employee_leaves(self, **_kwargs: str) -> SimpleNamespace:
                return SimpleNamespace(leave=leaves)

        monkeypatch.setattr(payroll_sdk, "payroll_api", _Api)

    def test_leave_inside_the_week_is_totalled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        week = payroll_push._WeekWindow.of(WEEK_START)
        self._stub(
            monkeypatch,
            [
                self._leave(WEEK_START, WEEK_START + timedelta(days=1), "8"),
                self._leave(WEEK_START + timedelta(days=2), WEEK_START + timedelta(days=2), "4"),
            ],
        )

        assert payroll_leave.posted_leave_hours(uuid.uuid4(), week, tenant_id="tenant") == Decimal(
            "12.000"
        )

    def test_leave_spanning_the_week_boundary_belongs_to_neither_week(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same containment rule the reconcile uses, so the two cannot disagree.

        Opus: Xero keeps one period per pay period, and a request straddling the
        boundary is not this week's to count — splitting it here would double
        it across two weeks.
        """
        week = payroll_push._WeekWindow.of(WEEK_START)
        self._stub(monkeypatch, [self._leave(WEEK_START - timedelta(days=1), WEEK_START, "8")])

        assert payroll_leave.posted_leave_hours(uuid.uuid4(), week, tenant_id="tenant") == Decimal(
            "0.000"
        )

    def test_an_unreadable_date_range_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Guessing which week undated leave belongs to would move someone's pay."""
        week = payroll_push._WeekWindow.of(WEEK_START)
        self._stub(monkeypatch, [self._leave(None, None, "8")])

        with pytest.raises(ValueError, match="unreadable date range"):
            payroll_leave.posted_leave_hours(uuid.uuid4(), week, tenant_id="tenant")


@pytest.mark.django_db
class TestWeekPostingStatus:
    """What Xero holds for a week, beside what the timesheet recorded.

    Opus: Both sides are carried and each is split timesheet vs leave, because the
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
        monkeypatch.setattr(
            payroll_push,
            "existing_timesheets_for_week",
            lambda _week, **_kwargs: timesheets,
        )
        monkeypatch.setattr(
            payroll_push, "timesheet_lines", lambda _id, **_kwargs: [_payload(posted_units)]
        )
        monkeypatch.setattr(
            payroll_push,
            "posted_leave_hours",
            lambda _employee, _week, **_kwargs: Decimal(leave_units),
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
            for row in payroll_push.week_posting_status(WEEK_START, tenant_id="tenant")
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
            for row in payroll_push.week_posting_status(WEEK_START, tenant_id="tenant")
            if row.staff_id == str(worker.id)
        ]

        assert status.posted is False
        assert status.recorded_timesheet_hours == Decimal("8.000")
        assert not status.matches

    def test_leave_is_counted_on_its_own_surface(
        self, monkeypatch: pytest.MonkeyPatch, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """Leave never appears on a timesheet, so a combined total misreads it."""
        leave_job = make_leave_job(company, superuser, "Annual Leave")
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
            for row in payroll_push.week_posting_status(WEEK_START, tenant_id="tenant")
            if row.staff_id == str(worker.id)
        ]

        assert status.recorded_leave_hours == Decimal("8.000")
        assert status.recorded_timesheet_hours == Decimal("0")
        assert status.posted_leave_hours == Decimal("8.000")
        assert status.matches

    def test_someone_who_left_before_the_week_is_not_reported(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """The same filter the weekly grid uses, so the two cannot disagree.

        Opus: This read used to roll its own — every row with a non-empty
        xero_user_id, no employment window — so it answered for people the grid
        never showed, and those rows could be matched against nothing.
        """
        worker.date_left = WEEK_START - timedelta(days=1)
        worker.save(update_fields=["date_left"])
        self._stub_xero(monkeypatch, timesheets={})

        reported = [
            row.staff_id for row in payroll_push.week_posting_status(WEEK_START, tenant_id="tenant")
        ]

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
        response = SimpleNamespace(timesheet=SimpleNamespace(timesheet_lines=lines))

        class _Api:
            def get_timesheet(self, **_kwargs: object) -> SimpleNamespace:
                return response

        monkeypatch.setattr(payroll_sdk, "payroll_api", _Api)

    def test_dated_lines_read_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub(monkeypatch, [self._dated()])

        [line] = payroll_push.timesheet_lines("ts-1", tenant_id="tenant")

        assert line.units == Decimal("8.000")

    def test_an_undated_line_is_refused_rather_than_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression: this used to return 8h and silently drop the rest."""
        undated = TimesheetLine(date=None, earnings_rate_id=None, number_of_units=None)
        self._stub(monkeypatch, [self._dated(), undated])

        with pytest.raises(ValueError, match="DELETED"):
            payroll_push.timesheet_lines("ts-1", tenant_id="tenant")


@pytest.mark.django_db
class TestLeaveFailureAbortsTheBatch:
    """v1 stops before creating a pay run or posting timesheets on leave failure."""

    def test_failure_escapes_and_no_timesheets_are_posted(
        self, monkeypatch: pytest.MonkeyPatch, xero_writes: list[str], worker: Staff, job: Job
    ) -> None:
        other = make_staff("payroll-push-other@example.com")
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(job, other, accounting_date=WEEK_START, hours="4.000")

        def _reconcile(employee_id: uuid.UUID, *_args: object, **_kwargs: object) -> None:
            if str(employee_id) == str(worker.xero_user_id):
                raise RuntimeError("Xero refused the leave request")

        monkeypatch.setattr(payroll_push, "reconcile_leave_for_staff_week", _reconcile)

        with pytest.raises(RuntimeError, match="Xero refused"):
            list(payroll_push.post_payroll_week(POSTING_TENANT, [worker.id, other.id], WEEK_START))

        # Opus: Nothing after the refresh. A pay run created here would hold the
        # half of the batch whose leave did reconcile, and Xero locks leave once
        # it exists — so the retry that fixes the failure could no longer run.
        assert xero_writes == ["refresh"]


class TestPayRunTenantIsolation:
    def test_refresh_deletes_only_orphans_for_the_connected_tenant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ours = make_pay_run("ours")
        foreign = make_pay_run("foreign")
        monkeypatch.setattr(
            payroll_push,
            "get_pay_runs_for_sync",
            lambda **_kwargs: SimpleNamespace(pay_runs=[]),
        )

        payroll_push.refresh_pay_runs(tenant_id="ours")

        assert not XeroPayRun.objects.filter(pk=ours.pk).exists()
        assert XeroPayRun.objects.filter(pk=foreign.pk).exists()

    def test_a_foreign_draft_does_not_block_this_tenant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calendar_id = uuid.uuid4()
        make_pay_run("foreign", calendar_id=calendar_id)
        monkeypatch.setattr(payroll_push, "_calendar_id", lambda: calendar_id)
        created = SimpleNamespace(pay_run_id="new-run")
        monkeypatch.setattr(payroll_push, "create_pay_run", lambda _week, **_kwargs: created)

        ensured = payroll_push.ensure_pay_run_for_week(WEEK_START, tenant_id="ours")

        assert ensured.pay_run_id == "new-run"

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

        def _transform(value: object, _xero_id: str, **_kwargs: object) -> tuple[object, str]:
            transformed.append(value)
            return mirrored, "created"

        monkeypatch.setattr(payroll_sdk, "payroll_api", lambda: api)
        monkeypatch.setattr(payroll_push, "get_payroll_calendars", lambda **_kwargs: [calendar])
        monkeypatch.setattr(payroll_push, "transform_pay_run", _transform)

        result = payroll_push.create_pay_run(WEEK_START, tenant_id="ours")

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
        # Fable: The SDK's generated setters refuse None for the required
        # fields, so a minimal-but-valid record is the smallest constructible one.
        existing = EmployeeLeave(
            leave_id="old-leave",
            leave_type_id="annual",
            description="Annual Leave",
            start_date=WEEK_START,
            end_date=WEEK_START,
        )
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
        # Fable: The SDK's generated setters refuse None for the required
        # fields, so a minimal-but-valid record is the smallest constructible one.
        existing = EmployeeLeave(
            leave_id="old-leave",
            leave_type_id="annual",
            description="Annual Leave",
            start_date=WEEK_START,
            end_date=WEEK_START,
        )
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


class TestReadonlyWeekPostsMirrorTheRealShape:
    """The read-only fake answers per pay_basis in the real provider's shape.

    Fable: The fake's docstring claims fidelity, and before these tests it
    answered a SALARIED week with ``success=True`` and a fabricated timesheet
    id — a shape the real provider never produces (salary is a skip in
    ``posting_mode="salary"`` with no timesheet) — and never set
    ``entries_posted``, ``other_leave_hours`` or ``posting_mode`` at all.
    """

    def test_a_salaried_week_is_a_salary_skip_not_a_fake_timesheet(self, job: Job) -> None:
        from apps.xero.readonly_provider import _suppressed_week_posts  # noqa: PLC0415

        salaried = make_staff("readonly-salaried@example.com", pay_basis="salary")
        make_time_line(job, salaried, accounting_date=WEEK_START, hours="8.000")

        [result] = list(_suppressed_week_posts([salaried.id], WEEK_START))

        assert result.success
        assert result.skipped, "the real provider never posts a salaried timesheet"
        assert result.posting_mode == "salary"
        assert result.timesheet_id is None
        assert result.reason == payroll_push.SALARY_SKIP_REASON
        assert result.work_hours == Decimal("8.000")
        assert result.salary_timesheet_removed is False
        assert result.has_entries

    def test_an_hourly_week_carries_the_real_result_fields(
        self, company: Company, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        from apps.xero.readonly_provider import _suppressed_week_posts  # noqa: PLC0415

        annual = make_leave_job(company, superuser, "Annual Leave")
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(
            annual, worker, accounting_date=WEEK_START + timedelta(days=1), hours="4.000"
        )

        [result] = list(_suppressed_week_posts([worker.id], WEEK_START))

        assert result.success
        assert not result.skipped
        assert result.posting_mode == "timesheet"
        assert result.timesheet_id, "an hourly week reports a (fake) posted timesheet"
        assert result.entries_posted == 2
        assert result.work_hours == Decimal("8.000")
        assert result.leave_hours == Decimal("4.000"), (
            "Leave-API hours must land in leave_hours, as the real split reports them"
        )
        assert result.other_leave_hours == Decimal("0")
