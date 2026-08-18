"""Tests for the payroll reconciliation service.

The ``get_aligned_date_range`` tests pin Monday-start/Sunday-end pay weeks and clamp the
start to ``CompanyDefaults.xero_payroll_start_date`` so the report never
covers weeks before Xero payroll history exists.

The reconciliation tests pin the per-staff week diff math
(``jm - xero`` sign convention), unmatched-staff handling on both sides, the
Posted-only pay-run filter, multi-pay-run weeks, cross-week aggregation, and
the ``xero_payroll_start_date`` window floor.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pytest
from django.apps import apps as django_apps
from django.db.models import Model

from apps.accounting.services import payroll_reconciliation_service
from apps.accounts.models import Staff
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import AppError, CompanyDefaults
from apps.job.models import Job
from apps.timesheet.tests.conftest import make_staff, make_time_line

pytestmark = [pytest.mark.django_db]

# The Monday/Sunday of the week most tests reconcile.
MONDAY = date(2026, 5, 4)
# The pay period IS the Monday-Sunday week: payroll_setup creates the calendar
# Monday-anchored and fails setup if Xero returns anything else.
XERO_PERIOD_START = date(2026, 5, 4)
XERO_PERIOD_END = date(2026, 5, 10)
PAYMENT_DATE = date(2026, 5, 12)
SYNC_TIME = datetime(2026, 5, 13, tzinfo=UTC)


def _set_payroll_start(payroll_start: date | None) -> None:
    defaults = CompanyDefaults.get_solo()
    CompanyDefaults.objects.filter(pk=defaults.pk).update(xero_payroll_start_date=payroll_start)


def _aligned(start: date, end: date) -> tuple[date, date]:
    result = payroll_reconciliation_service.get_aligned_date_range(start, end)
    return result["aligned_start"], result["aligned_end"]


class TestGetAlignedDateRange:
    """Pay-period boundary alignment behavior."""

    def test_midweek_dates_snap_to_monday_and_sunday(self) -> None:
        _set_payroll_start(None)
        # Tuesday 2025-04-01 -> Monday 2025-03-31; Tuesday 2026-03-31 -> Sunday 2026-04-05
        aligned_start, aligned_end = _aligned(date(2025, 4, 1), date(2026, 3, 31))
        assert aligned_start == date(2025, 3, 31)
        assert aligned_end == date(2026, 4, 5)

    def test_already_aligned_dates_are_unchanged(self) -> None:
        _set_payroll_start(None)
        # Monday 2025-03-31 and Sunday 2026-04-05 are already week boundaries
        aligned_start, aligned_end = _aligned(date(2025, 3, 31), date(2026, 4, 5))
        assert aligned_start == date(2025, 3, 31)
        assert aligned_end == date(2026, 4, 5)

    def test_single_day_expands_to_its_full_week(self) -> None:
        _set_payroll_start(None)
        # Thursday 2025-04-03 -> the whole Mon-Sun week containing it
        aligned_start, aligned_end = _aligned(date(2025, 4, 3), date(2025, 4, 3))
        assert aligned_start == date(2025, 3, 31)
        assert aligned_end == date(2025, 4, 6)

    def test_start_clamps_to_payroll_start_before_snapping(self) -> None:
        # Friday 2025-08-01: requests starting earlier clamp to it, then
        # snap to the Monday of its week.
        _set_payroll_start(date(2025, 8, 1))
        aligned_start, aligned_end = _aligned(date(2025, 4, 1), date(2026, 3, 31))
        assert aligned_start == date(2025, 7, 28)
        assert aligned_end == date(2026, 4, 5)

    def test_start_after_payroll_start_is_not_clamped(self) -> None:
        _set_payroll_start(date(2025, 8, 1))
        # Tuesday 2025-09-02 is after the payroll start -> normal Monday snap
        aligned_start, _ = _aligned(date(2025, 9, 2), date(2026, 3, 31))
        assert aligned_start == date(2025, 9, 1)

    def test_payroll_start_on_a_monday_clamps_exactly_to_it(self) -> None:
        _set_payroll_start(date(2025, 8, 4))  # a Monday
        aligned_start, _ = _aligned(date(2025, 4, 1), date(2026, 3, 31))
        assert aligned_start == date(2025, 8, 4)

    def test_end_date_is_never_clamped_by_payroll_start(self) -> None:
        # The clamp applies to the start only; an end before payroll start
        # still snaps to its own week's Sunday (yielding an empty range,
        # which the report handles, rather than a silently rewritten end).
        _set_payroll_start(date(2025, 8, 1))
        _, aligned_end = _aligned(date(2025, 4, 1), date(2025, 5, 1))
        assert aligned_end == date(2025, 5, 4)


# ---------------------------------------------------------------------------
# Reconciliation fixtures — XeroPayRun/XeroPaySlip are reached through the app
# registry: the layer contract forbids apps.accounting -> apps.xero imports.
# ---------------------------------------------------------------------------


def _make_pay_run(
    *,
    start: date = XERO_PERIOD_START,
    end: date = XERO_PERIOD_END,
    payment: date = PAYMENT_DATE,
    status: str = "Posted",
) -> Model:
    # The registry manager is untyped (Any); the cast carries the Model typing,
    # as the service's protocol cast does for the same layer-contract seam.
    return cast(
        "Model",
        django_apps.get_model("xero", "XeroPayRun")._default_manager.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id="tenant-1",
            period_start_date=start,
            period_end_date=end,
            payment_date=payment,
            pay_run_status=status,
            raw_json={},
            xero_last_modified=SYNC_TIME,
        ),
    )


def _make_pay_slip(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
    pay_run: Model,
    *,
    employee_id: uuid.UUID | None = None,
    employee_name: str | None = "Xero Employee",
    timesheet_hours: str = "0",
    leave_hours: str = "0",
    gross: str = "0",
) -> Model:
    return cast(
        "Model",
        django_apps.get_model("xero", "XeroPaySlip")._default_manager.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id="tenant-1",
            pay_run=pay_run,
            xero_employee_id=employee_id if employee_id is not None else uuid.uuid4(),
            employee_name=employee_name,
            gross_earnings=Decimal(gross),
            timesheet_hours=Decimal(timesheet_hours),
            leave_hours=Decimal(leave_hours),
            raw_json={},
            xero_last_modified=SYNC_TIME,
        ),
    )


@pytest.fixture
def job() -> Job:
    company = make_company("Payroll Reconciliation Co")
    creator = make_staff("payroll-recon-admin@example.com", is_office_staff=True, is_superuser=True)
    return make_job(company, creator, name="Payroll Reconciliation Job")


@pytest.fixture
def wendy(job: Job) -> Staff:
    """A staff member linked to Xero: JM lines cost 48.00/h (40.00 + 20% loading)."""
    assert job is not None  # CompanyDefaults exists before Staff.save() reads it
    return make_staff("payroll-recon-wendy@example.com", first_name="Wendy", last_name="Workshop")


def _wendy_slip_employee_id(wendy: Staff) -> uuid.UUID:
    assert wendy.xero_user_id is not None
    return uuid.UUID(wendy.xero_user_id)


class TestWeekDiffMath:
    def test_matched_staff_row_computes_jm_minus_xero_diffs(self, job: Job, wendy: Staff) -> None:
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="6",
            leave_hours="2",
            gross="400",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [week] = data["weeks"]
        assert week["week_start"] == "2026-05-04"
        assert week["xero_period_start"] == "2026-05-04"
        assert week["xero_period_end"] == "2026-05-10"
        assert week["payment_date"] == "2026-05-12"
        [row] = week["staff"]
        assert row["name"] == "Wendy Workshop"
        assert row["xero_hours"] == 8.0
        assert row["xero_timesheet_hours"] == 6.0
        assert row["xero_leave_hours"] == 2.0
        assert row["xero_gross"] == 400.0
        assert row["xero_rate"] == 50.0
        assert row["jm_hours"] == 8.0
        assert row["jm_cost"] == 384.0  # 8h at the 48.00 loaded wage rate
        assert row["jm_rate"] == 48.0
        assert row["hours_diff"] == 0.0
        assert row["cost_diff"] == -16.0  # jm - xero: JM cheaper is negative
        assert row["hours_cost_impact"] == 0.0
        assert row["rate_cost_impact"] == -16.0
        assert row["status"] == "mismatch"  # |diff| above the 0.50 threshold
        assert week["mismatch_count"] == 1
        assert week["totals"] == {
            "xero_gross": 400.0,
            "jm_cost": 384.0,
            "diff": -16.0,
            "xero_hours": 8.0,
            "jm_hours": 8.0,
        }
        assert data["grand_totals"] == {
            "xero_gross": 400.0,
            "jm_cost": 384.0,
            "diff": -16.0,
            "diff_pct": -4.0,
        }

    def test_base_pay_drops_the_leave_loading_so_it_is_comparable_to_gross(
        self, job: Job, wendy: Staff
    ) -> None:
        """``jm_cost`` cannot be compared with Xero's gross; ``jm_base_pay`` can.

        The costing pipeline prices time at the LOADED rate (48.00 = Wendy's
        40.00 base plus 20% annual leave loading), because that is what the job
        is charged. Xero pays the base rate. Comparing ``jm_cost`` against
        ``xero_gross`` therefore reports every employee as 20% wrong every
        week, which buries the errors that are real — so the reconciliation
        needs the loading removed before it subtracts.

        Here Xero pays exactly what it should: 8h at 40.00.
        """
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="8",
            gross="320",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [row] = data["weeks"][0]["staff"]
        assert row["jm_cost"] == 384.0  # 8h at the loaded 48.00: what the job paid
        assert row["jm_base_pay"] == 320.0  # 8h at the base 40.00: what payroll owes
        assert row["xero_gross"] == 320.0
        assert row["pay_diff"] == 0.0  # payroll is correct, and says so
        assert row["cost_diff"] == 64.0  # the loading alone — not an error

    def test_base_pay_survives_the_loading_being_changed_afterwards(
        self, job: Job, wendy: Staff
    ) -> None:
        """Base pay comes from the line's own rate, never from today's setting.

        ``CostLine.unit_cost`` is denormalised at write time and frozen; the
        annual leave loading is a setting that can change at any moment. So
        recovering base pay by dividing the cost by the CURRENT loading is
        wrong for every line written under a different one — which is every
        line in the restored data, priced at 1.08 while the column now reads
        20.00. Wendy's 8h stay worth 8h at her 40.00 base whatever the loading
        does afterwards.
        """
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="8",
            gross="320",
        )

        defaults = CompanyDefaults.get_solo()
        defaults.annual_leave_loading = Decimal("50.00")
        defaults.save()

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [row] = data["weeks"][0]["staff"]
        assert row["jm_base_pay"] == 320.0
        assert row["pay_diff"] == 0.0
        assert row["status"] == "ok"

    def test_two_staff_sharing_a_display_name_stay_two_rows(self, job: Job, wendy: Staff) -> None:
        """The join key is the Xero employee id, not a first name.

        ``get_display_name`` returns the first word only, so two people called
        Mei-Lin collapse into one row while Xero holds a pay slip for each —
        merging their money and hiding whichever of them is the finding.
        """
        twin = make_staff(
            "payroll-recon-wendy-twin@example.com",
            first_name="Wendy",
            last_name="Wharehouse",
        )
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")
        make_time_line(job, twin, accounting_date=date(2026, 5, 5), hours="4.000")
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="8",
            gross="320",
        )
        _make_pay_slip(
            pay_run,
            employee_id=uuid.UUID(str(twin.xero_user_id)),
            timesheet_hours="4",
            gross="160",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        rows = data["weeks"][0]["staff"]
        assert len(rows) == 2
        assert sorted(row["xero_gross"] for row in rows) == [160.0, 320.0]
        assert all(row["status"] == "ok" for row in rows)

    def test_jm_exceeding_xero_yields_positive_diffs_split_into_impacts(
        self, job: Job, wendy: Staff
    ) -> None:
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="10.000")
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="8",
            gross="400",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [row] = data["weeks"][0]["staff"]
        assert row["hours_diff"] == 2.0  # jm 10h - xero 8h
        assert row["cost_diff"] == 80.0  # jm 480 - xero 400
        # The extra 2 JM hours at the Xero rate (50/h) explain 100 of the diff;
        # the JM rate being 2.00/h cheaper claws back 20.
        assert row["hours_cost_impact"] == 100.0
        assert row["rate_cost_impact"] == -20.0

    def test_a_week_tracking_xero_within_tolerance_is_ok(self, job: Job, wendy: Staff) -> None:
        """Close, not equal: DocketWorks is a management figure and Xero is exact.

        8h at Wendy's 40.00 base is 320.00; Xero paid 322.00, which is inside
        the proportional band. Judged on BASE pay against the gross — the two
        figures that describe the same thing — rather than on the loaded wage,
        which carries the annual leave loading Xero never pays.
        """
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="8",
            gross="322.00",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [week] = data["weeks"]
        row = week["staff"][0]
        assert row["jm_base_pay"] == 320.0
        assert row["jm_cost"] == 384.0  # the loaded wage, 20% above what Xero pays
        assert row["status"] == "ok"
        assert week["mismatch_count"] == 0


class TestUnmatchedStaff:
    def test_jm_only_staff_shows_zero_xero_side(self, job: Job, wendy: Staff) -> None:
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [week] = data["weeks"]
        assert week["xero_period_start"] is None
        assert week["xero_period_end"] is None
        assert week["payment_date"] is None
        [row] = week["staff"]
        assert row["name"] == "Wendy Workshop"
        assert row["status"] == "jm_only"
        assert row["xero_hours"] == 0.0
        assert row["xero_gross"] == 0.0
        assert row["xero_rate"] == 0.0
        assert row["cost_diff"] == 384.0
        assert week["mismatch_count"] == 1

    def test_xero_only_slip_without_matching_staff_uses_the_slip_name(
        self, job: Job, wendy: Staff
    ) -> None:
        # Wendy exists but the slip belongs to an employee id no Staff carries.
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_name="Departed Person",
            timesheet_hours="4",
            gross="200",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [week] = data["weeks"]
        by_name = {row["name"]: row for row in week["staff"]}
        departed = by_name["Departed Person"]
        assert departed["status"] == "xero_only_unknown"
        assert departed["jm_hours"] == 0.0
        assert departed["jm_cost"] == 0.0
        assert departed["cost_diff"] == -200.0
        assert by_name["Wendy Workshop"]["status"] == "jm_only"
        assert week["mismatch_count"] == 2

    def test_a_departed_staff_member_xero_still_pays_is_named_as_such(
        self, job: Job, wendy: Staff
    ) -> None:
        """The finding: we recorded them gone and Xero is still paying them.

        Distinguished from an unknown employee because the action differs — run
        their final pay in Xero and terminate them there — and from a salaried
        one, who has no cost lines by design and is not a finding at all.
        """
        assert job is not None
        wendy.date_left = date(2026, 4, 30)
        wendy.save(update_fields=["date_left"])
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="40",
            gross="1600",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [row] = data["weeks"][0]["staff"]
        assert row["status"] == "xero_only_departed"
        assert row["xero_gross"] == 1600.0

    def test_a_salaried_employee_is_expected_not_a_finding(self, job: Job, wendy: Staff) -> None:
        """Salaried staff have no cost lines by design, so they are not a gap.

        ``time_entry_rates.staff_wage_rate`` refuses to price a salaried
        person's time without an explicit override, so DocketWorks books
        nothing while Xero pays them every week. Sharing a bucket with departed
        staff would make every salaried employee a false alarm every week and
        drown the real signal.
        """
        assert job is not None
        wendy.pay_basis = "salary"
        wendy.save(update_fields=["pay_basis"])
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="40",
            gross="2000",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [row] = data["weeks"][0]["staff"]
        assert row["status"] == "xero_only_salaried"

    def test_slip_with_no_name_and_no_staff_match_fails_loudly(self, job: Job) -> None:
        assert job is not None  # seeds CompanyDefaults for get_reconciliation_data
        pay_run = _make_pay_run()
        _make_pay_slip(pay_run, employee_name=None, timesheet_hours="4", gross="200")

        with pytest.raises(ValueError, match="no employee_name"):
            payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        # The handler persisted the failure with the report's business context.
        [app_error] = AppError.objects.all()
        assert app_error.data is not None
        assert app_error.data["operation"] == "payroll_reconciliation"


class TestWeekDiscovery:
    def test_draft_pay_runs_are_ignored(self, job: Job, wendy: Staff) -> None:
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")
        pay_run = _make_pay_run(status="Draft")
        _make_pay_slip(
            pay_run,
            employee_id=_wendy_slip_employee_id(wendy),
            timesheet_hours="8",
            gross="400",
        )

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [week] = data["weeks"]
        assert week["xero_period_start"] is None  # the Draft run contributed nothing
        assert week["staff"][0]["status"] == "jm_only"

    def test_multiple_pay_runs_in_one_week_are_summed(self, wendy: Staff) -> None:
        employee_id = _wendy_slip_employee_id(wendy)
        scheduled = _make_pay_run()
        _make_pay_slip(scheduled, employee_id=employee_id, timesheet_hours="8", gross="400")
        unscheduled = _make_pay_run(
            start=date(2026, 5, 4), end=date(2026, 5, 8), payment=date(2026, 5, 13)
        )
        _make_pay_slip(unscheduled, employee_id=employee_id, timesheet_hours="2", gross="100")

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 10))

        [week] = data["weeks"]
        assert week["xero_period_start"] == "2026-05-04"  # earliest across runs
        assert week["xero_period_end"] == "2026-05-10"  # latest across runs
        assert week["payment_date"] == "2026-05-13"  # latest across runs
        [row] = week["staff"]
        assert row["xero_hours"] == 10.0
        assert row["xero_gross"] == 500.0

    def test_window_floor_drops_weeks_before_xero_payroll_start(
        self, job: Job, wendy: Staff
    ) -> None:
        _set_payroll_start(MONDAY)
        make_time_line(job, wendy, accounting_date=date(2026, 4, 28), hours="8.000")
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")

        data = payroll_reconciliation_service.get_reconciliation_data(
            date(2026, 4, 27), date(2026, 5, 10)
        )

        assert [week["week_start"] for week in data["weeks"]] == ["2026-05-04"]


class TestCrossWeekAggregation:
    def test_staff_summaries_and_heatmap_aggregate_across_weeks(self, job: Job) -> None:
        wendy = make_staff(
            "payroll-recon-wendy@example.com", first_name="Wendy", last_name="Workshop"
        )
        otto = make_staff("payroll-recon-otto@example.com", first_name="Otto", last_name="Other")
        make_time_line(job, wendy, accounting_date=date(2026, 5, 5), hours="8.000")
        make_time_line(job, wendy, accounting_date=date(2026, 5, 12), hours="8.000")
        make_time_line(job, otto, accounting_date=date(2026, 5, 5), hours="8.000")

        data = payroll_reconciliation_service.get_reconciliation_data(MONDAY, date(2026, 5, 17))

        assert [week["week_start"] for week in data["weeks"]] == ["2026-05-04", "2026-05-11"]
        by_name = {s["name"]: s for s in data["staff_summaries"]}
        assert by_name["Wendy Workshop"]["weeks_present"] == 2
        assert by_name["Wendy Workshop"]["weeks_with_mismatch"] == 2  # jm_only counts as a mismatch
        assert by_name["Wendy Workshop"]["jm_hours"] == 16.0
        assert by_name["Wendy Workshop"]["cost_diff"] == 768.0
        assert by_name["Otto Other"]["weeks_present"] == 1

        assert data["heatmap"]["staff_names"] == ["Otto Other", "Wendy Workshop"]
        week_two = data["heatmap"]["rows"][1]
        assert week_two["week_start"] == "2026-05-11"
        assert week_two["cells"] == {"Otto Other": None, "Wendy Workshop": 384.0}
