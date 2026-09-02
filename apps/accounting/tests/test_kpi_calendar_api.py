"""Business-behaviour tests for GET /api/accounting/reports/calendar/.

June 2026 is the fixture month: fully elapsed, contains King's
Birthday (Mon 1 June) and 22 working days.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import (
    make_job,
    make_material_line,
)
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.timesheet.tests.conftest import make_staff, make_time_line

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

URL = "/api/accounting/reports/calendar/"
JUNE = {"year": "2026", "month": "6"}
WORKDAY = date(2026, 6, 10)  # a Wednesday


@pytest.fixture
def thresholds() -> CompanyDefaults:
    defaults = CompanyDefaults.get_solo()
    defaults.kpi_daily_billable_hours_green = Decimal("8")
    defaults.kpi_daily_billable_hours_amber = Decimal("5")
    defaults.kpi_daily_gp_target = Decimal("1000.00")
    defaults.kpi_daily_gp_green = Decimal("500.00")
    defaults.kpi_daily_gp_amber = Decimal("250.00")
    defaults.save()
    return defaults


def add_material_line(job: Job, *, on: date, rev: str, cost: str) -> object:
    return make_material_line(job, rev=rev, cost=cost, on=on)


@pytest.mark.usefixtures("thresholds")
class TestKPICalendar:
    def test_requires_authentication(self) -> None:
        assert Client().get(URL, JUNE).status_code == 401

    def test_out_of_range_month_is_rejected(self, authenticated_client: Client) -> None:
        assert authenticated_client.get(URL, {"year": "2026", "month": "13"}).status_code == 422
        assert authenticated_client.get(URL, {"year": "1999", "month": "6"}).status_code == 422

    def test_day_metrics_and_colors(self, authenticated_client: Client) -> None:
        worker = make_staff("kpi@example.com")
        company = make_company("KPI Co")
        job = make_job(company, worker)

        # 6 billable hours (amber: >=5, <8), $120/h rev, $40/h cost
        make_time_line(
            job,
            worker,
            accounting_date=WORKDAY,
            hours="6.000",
            unit_cost="40.00",
            unit_rev="120.00",
        )
        add_material_line(job, on=WORKDAY, rev="400.00", cost="150.00")

        body = authenticated_client.get(URL, JUNE).json()
        day = body["calendar_data"]["2026-06-10"]
        assert day["billable_hours"] == 6.0
        assert day["total_hours"] == 6.0
        # Both ladders ship and each reads its own input: 6 billable hours is
        # amber against the 8/5 hours rungs, and $730 gross profit is amber
        # against the $1,000 overhead it did not quite cover. The report
        # chooses which one tints the calendar.
        assert day["color_hours"] == "amber"
        assert day["color_gp"] == "amber"
        assert day["gp_target_achievement"] == 73.0
        # GP = time rev 720 - staff cost 240 + material 400-150
        assert day["gross_profit"] == 720.0 - 240.0 + 250.0
        details = day["details"]
        assert details["time_revenue"] == 720.0
        assert details["material_revenue"] == 400.0
        assert details["total_cost"] == 390.0
        assert details["profit_breakdown"]["labour_profit"] == 480.0
        breakdown = details["job_breakdown"]
        assert breakdown[0]["job_number"] == str(job.job_number)
        assert breakdown[0]["profit"] == 730.0

        assert body["thresholds"]["kpi_daily_billable_hours_green"] == 8.0
        assert body["year"] == 2026
        assert body["month"] == 6

    def test_the_two_day_ladders_can_disagree(self, authenticated_client: Client) -> None:
        """Few hours, good money — red by hours, green by dollars.

        This is why both ship. v1 tinted only by hours, deliberately: dollars
        are the goal but a noisy daily signal, while billed hours lead them.
        A viewer who wants the dollars view must not have it recomputed in the
        browser off a forked ladder.
        """
        worker = make_staff("ladders@example.com")
        job = make_job(make_company("Ladders Co"), worker)
        # 2 billable hours: red on the 8/5 hours rungs.
        make_time_line(
            job,
            worker,
            accounting_date=WORKDAY,
            hours="2.000",
            unit_cost="40.00",
            unit_rev="120.00",
        )
        # ...but a fat material margin clears the $1,000 overhead on its own.
        add_material_line(job, on=WORKDAY, rev="1400.00", cost="200.00")

        day = authenticated_client.get(URL, JUNE).json()["calendar_data"]["2026-06-10"]
        assert day["color_hours"] == "red"
        assert day["color_gp"] == "green"

    def test_weekends_excluded_and_holidays_flagged_but_counted_as_working_days(
        self, authenticated_client: Client
    ) -> None:
        body = authenticated_client.get(URL, JUNE).json()
        days = body["calendar_data"]
        assert "2026-06-06" not in days  # Saturday
        assert "2026-06-07" not in days  # Sunday
        assert body["weekend_enabled"] is False
        kings_birthday = days["2026-06-01"]
        assert kings_birthday["holiday"] is True
        assert kings_birthday["holiday_name"]
        # v1 counts holidays as working days (the sales-pipeline report makes
        # the opposite call — recorded divergence, ported faithfully).
        assert body["monthly_totals"]["working_days"] == 22

    def test_weekend_flag_adds_saturday_and_sunday_as_working_days(
        self, authenticated_client: Client, thresholds: CompanyDefaults
    ) -> None:
        thresholds.weekend_timesheets_enabled = True
        thresholds.save()

        body = authenticated_client.get(URL, JUNE).json()
        days = body["calendar_data"]
        assert body["weekend_enabled"] is True
        assert "2026-06-06" in days  # Saturday
        assert "2026-06-07" in days  # Sunday
        # June 2026's 22 weekdays plus its 8 weekend days.
        assert body["monthly_totals"]["working_days"] == 30

    def test_weekend_work_reaches_the_month_whatever_the_flag_says(
        self, authenticated_client: Client, thresholds: CompanyDefaults
    ) -> None:
        """The flag governs the cells drawn, never the money counted.

        A Saturday's lines still count in WIP and job costing, so a KPI month
        that dropped them would disagree with those reports about the same
        job. With weekends off the day has no cell to appear in — the money
        reaches the monthly total and nothing else.
        """
        worker = make_staff("weekend@example.com")
        company = make_company("Weekend Co")
        job = make_job(company, worker)
        saturday = date(2026, 6, 13)
        make_time_line(
            job,
            worker,
            accounting_date=saturday,
            hours="8.000",
            unit_cost="40.00",
            unit_rev="120.00",
        )

        body = authenticated_client.get(URL, JUNE).json()
        off = body["monthly_totals"]
        assert off["billable_hours"] == 8.0
        assert off["gross_profit"] == 8 * (120.0 - 40.0)
        assert "2026-06-13" not in body["calendar_data"]  # counted, not drawn

        thresholds.weekend_timesheets_enabled = True
        thresholds.save()

        body = authenticated_client.get(URL, JUNE).json()
        on = body["monthly_totals"]
        assert on["billable_hours"] == off["billable_hours"]
        assert on["gross_profit"] == off["gross_profit"]
        assert "2026-06-13" in body["calendar_data"]  # now drawn too

    def test_showing_weekends_moves_no_money_figure(
        self, authenticated_client: Client, thresholds: CompanyDefaults
    ) -> None:
        """Weekend work is bonus, not baseline.

        Overhead is the month's opex spread across its weekdays, so no share
        of it lands on a Saturday. Switching the weekend columns on adds
        cells and nothing else: an empty weekend contributes $0 of gross
        profit and must also add $0 of target. If this fails, a shop that
        turned on weekend visibility just had its monthly overhead raised by
        a third and its average GP cut by a quarter.
        """
        worker = make_staff("bonus@example.com")
        job = make_job(make_company("Bonus Co"), worker)
        # Weekdays only, so every weekend day in the month is genuinely empty.
        for day in (10, 11, 12):  # Wed, Thu, Fri
            make_time_line(
                job,
                worker,
                accounting_date=date(2026, 6, day),
                hours="8.000",
                unit_cost="40.00",
                unit_rev="120.00",
            )

        off = authenticated_client.get(URL, JUNE).json()["monthly_totals"]
        thresholds.weekend_timesheets_enabled = True
        thresholds.save()
        on = authenticated_client.get(URL, JUNE).json()["monthly_totals"]

        for field in (
            "days_green",
            "days_amber",
            "days_red",
            "labour_red_days",
            "profit_red_days",
            "gross_profit",
            "labour_profit",
            "total_revenue",
            "total_cost",
            "elapsed_target",
            "net_profit",
            "avg_weekday_gp",
            "avg_active_day_gp",
            "avg_active_day_billable_hours",
            "weekdays",
            "elapsed_weekdays",
            "color_gp",
            "color_hours",
        ):
            assert off[field] == on[field], field

        # What legitimately does change: the calendar gained real cells, and
        # empty ones are below threshold like any other unworked day.
        assert off["working_days"] == 22
        assert on["working_days"] == 30

    def test_a_weekend_cell_carries_money_but_no_grade(
        self, authenticated_client: Client, thresholds: CompanyDefaults
    ) -> None:
        """$0 earned against $0 owed is blank, not red.

        A weekend is never apportioned overhead, so it cannot fall short of
        it. Grading an untouched Saturday red would let a display setting
        turn a good month into a bad-looking one.
        """
        thresholds.weekend_timesheets_enabled = True
        thresholds.save()

        days = authenticated_client.get(URL, JUNE).json()["calendar_data"]
        saturday = days["2026-06-06"]
        assert saturday["color_hours"] == "weekend"
        assert saturday["color_gp"] == "weekend"
        # The achievement IS null: no target means no denominator.
        assert saturday["gp_target_achievement"] is None
        assert saturday["gross_profit"] == 0.0

        # A weekday with nothing on it DID fall short of its overhead.
        assert days["2026-06-11"]["color_hours"] == "red"
        assert days["2026-06-11"]["gp_target_achievement"] == 0.0

    def test_monthly_totals_roll_up_elapsed_performance(self, authenticated_client: Client) -> None:
        worker = make_staff("totals@example.com")
        company = make_company("Totals Co")
        job = make_job(company, worker)
        # One green day: 8 billable hours, GP 8*(120-40) = 640 + material 500
        make_time_line(
            job,
            worker,
            accounting_date=WORKDAY,
            hours="8.000",
            unit_cost="40.00",
            unit_rev="120.00",
        )
        add_material_line(job, on=WORKDAY, rev="600.00", cost="100.00")

        totals = authenticated_client.get(URL, JUNE).json()["monthly_totals"]
        assert totals["billable_hours"] == 8.0
        assert totals["gross_profit"] == 640.0 + 500.0
        # The three profit components are served, so no client subtracts them:
        # 8h x (120 - 40) labour, and 600 - 100 material.
        assert totals["labour_profit"] == 640.0
        assert totals["material_profit"] == 500.0
        assert totals["labour_profit"] + totals["material_profit"] == totals["gross_profit"]
        assert totals["days_green"] == 1
        assert totals["days_red"] == 21  # every other working day had no hours
        assert totals["active_days"] == 1  # only days with hours count
        # June 2026 is fully elapsed. Net profit is gross profit less the
        # overhead incurred: the daily GP target IS the opex share, charged
        # across the month's 22 WEEKDAYS.
        assert totals["elapsed_workdays"] == 22
        assert totals["elapsed_weekdays"] == 22
        assert totals["net_profit"] == (640.0 + 500.0) - 1000.0 * 22
        # Averages divide by active workdays so idle days don't dilute them.
        assert totals["avg_active_day_billable_hours"] == 8.0
        assert totals["color_hours"] == "green"

    def test_a_worked_weekend_counts_in_the_divisor_it_earns_into(
        self, authenticated_client: Client, thresholds: CompanyDefaults
    ) -> None:
        """avg_active_day_* must divide by every day that carried hours.

        The money already includes a worked Saturday whatever the flag says,
        so a divisor counting weekdays alone put seven days of earnings over
        five days of count. The month's own colour is read off these averages,
        so amber weekdays plus busy Saturdays graded the month green without a
        single green day in it.
        """
        worker = make_staff("divisor@example.com")
        company = make_company("Divisor Co")
        job = make_job(company, worker)
        for worked in (date(2026, 6, 12), date(2026, 6, 13)):  # Friday, then Saturday
            make_time_line(
                job,
                worker,
                accounting_date=worked,
                hours="8.000",
                unit_cost="40.00",
                unit_rev="120.00",
            )

        off = authenticated_client.get(URL, JUNE).json()["monthly_totals"]

        assert off["billable_hours"] == 16.0
        assert off["active_days"] == 2
        assert off["avg_active_day_billable_hours"] == 8.0
        assert off["avg_active_day_gp"] == 8 * (120.0 - 40.0)

        thresholds.weekend_timesheets_enabled = True
        thresholds.save()
        on = authenticated_client.get(URL, JUNE).json()["monthly_totals"]

        assert on["active_days"] == off["active_days"]
        assert on["avg_active_day_gp"] == off["avg_active_day_gp"]
        assert on["avg_active_day_billable_hours"] == off["avg_active_day_billable_hours"]

    def test_the_weekday_counters_do_not_move_when_weekend_cells_appear(
        self,
        authenticated_client: Client,
        thresholds: CompanyDefaults,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """remaining_weekdays is the counter target arithmetic may multiply.

        Placed mid-month so the month has a future to have remaining days in.
        The service's own "today" is patched rather than the clock: freezing
        time invalidates the session the authenticated client holds, and this
        is the only date the calculation reads.
        working_days counts drawn cells, so it and remaining_workdays swing
        when the display flag flips; multiplying remaining_workdays by
        kpi_daily_gp_target claims four more days of overhead still to cover
        than the business owes. The weekday counters do not move, which is
        what makes them the safe ones to multiply.
        """
        monkeypatch.setattr(timezone, "localdate", lambda: date(2026, 6, 15))
        off = authenticated_client.get(URL, JUNE).json()["monthly_totals"]

        thresholds.weekend_timesheets_enabled = True
        thresholds.save()
        on = authenticated_client.get(URL, JUNE).json()["monthly_totals"]

        # June 2026 starts on a Monday: 22 weekdays, 8 weekend days, and by the
        # 15th eleven weekdays and four weekend days have elapsed.
        assert off["remaining_workdays"] == 11
        assert on["remaining_workdays"] == 15
        assert off["remaining_weekdays"] == on["remaining_weekdays"] == 11
        assert on["weekdays"] == off["weekdays"] == 22
        assert on["elapsed_weekdays"] == off["elapsed_weekdays"] == 11
