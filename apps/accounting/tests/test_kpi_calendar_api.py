"""Business-behaviour tests for GET /api/accounting/reports/calendar/.

June 2026 is the fixture month: fully elapsed, contains King's
Birthday (Mon 1 June) and 22 working days.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

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
        assert day["color"] == "amber"
        # GP = time rev 720 - staff cost 240 + material 400-150
        assert day["gross_profit"] == 720.0 - 240.0 + 250.0
        details = day["details"]
        assert details["time_revenue"] == 720.0
        assert details["material_revenue"] == 400.0
        assert details["total_cost"] == 390.0
        assert details["profit_breakdown"]["labor_profit"] == 480.0
        breakdown = details["job_breakdown"]
        assert breakdown[0]["job_number"] == str(job.job_number)
        assert breakdown[0]["profit"] == 730.0

        assert body["thresholds"]["kpi_daily_billable_hours_green"] == 8.0
        assert body["year"] == 2026
        assert body["month"] == 6

    def test_weekends_excluded_and_holidays_flagged_but_counted_as_working_days(
        self, authenticated_client: Client
    ) -> None:
        body = authenticated_client.get(URL, JUNE).json()
        days = body["calendar_data"]
        assert "2026-06-06" not in days  # Saturday
        assert "2026-06-07" not in days  # Sunday
        kings_birthday = days["2026-06-01"]
        assert kings_birthday["holiday"] is True
        assert kings_birthday["holiday_name"]
        # v1 counts holidays as working days (the sales-pipeline report makes
        # the opposite call — recorded divergence, ported faithfully).
        assert body["monthly_totals"]["working_days"] == 22

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
        assert totals["days_green"] == 1
        assert totals["days_red"] == 21  # every other working day had no hours
        assert totals["active_workdays"] == 1  # only days with hours count
        # June 2026 fully elapsed by 2026-08: net = GP - target x working days
        assert totals["elapsed_workdays"] == 22
        assert totals["net_profit"] == (640.0 + 500.0) - 1000.0 * 22
        # Averages divide by active workdays so idle days don't dilute them.
        assert totals["avg_billable_hours_so_far"] == 8.0
        assert totals["color_hours"] == "green"
