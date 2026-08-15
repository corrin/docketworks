"""The payroll push's decisions, isolated from Xero.

These cover the rules that are easy to get subtly wrong and expensive to
discover afterwards: how lines are routed between Xero's two payroll APIs, how
leave runs are shaped, and when a re-post is a no-op. The Xero calls themselves
are the E2E spec's job against the demo company.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.tests.conftest import WEEK_START, make_staff, make_time_line
from apps.xero import payroll_leave, payroll_push

pytestmark = pytest.mark.django_db


# The staff/company/job factories live with the timesheet fixtures; these wire
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
        with pytest.raises(ValueError, match="must be a Monday"):
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
        assert payloads[0]["date"] == WEEK_START
        assert payloads[0]["number_of_units"] == pytest.approx(7.5)


class TestRepostIsANoOp:
    def test_matching_lines_are_recognised(self) -> None:
        existing = [
            SimpleNamespace(date=WEEK_START, earnings_rate_id="rate-1", number_of_units=8.0)
        ]
        incoming = [{"date": WEEK_START, "earnings_rate_id": "rate-1", "number_of_units": 8.0}]

        assert payroll_push._lines_match(existing, incoming) is True

    def test_changed_hours_are_not_matching(self) -> None:
        existing = [
            SimpleNamespace(date=WEEK_START, earnings_rate_id="rate-1", number_of_units=8.0)
        ]
        incoming = [{"date": WEEK_START, "earnings_rate_id": "rate-1", "number_of_units": 7.5}]

        assert payroll_push._lines_match(existing, incoming) is False

    def test_comparison_tolerates_float_representation(self) -> None:
        """Both sides are rounded to 2dp; 8.000000001 is the same eight hours."""
        existing = [
            SimpleNamespace(date=WEEK_START, earnings_rate_id="rate-1", number_of_units=8.000000001)
        ]
        incoming = [{"date": WEEK_START, "earnings_rate_id": "rate-1", "number_of_units": 8.0}]

        assert payroll_push._lines_match(existing, incoming) is True


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
