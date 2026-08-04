"""Business-behaviour tests for the staff-performance report endpoints.

Pins the calculations v1 never tested: billable % (shop-company work is never
billable), per-hour rates, the no-hours filter, and the detail view's job
breakdown + 404 contract.
"""

from datetime import date

import pytest
from django.test import Client

from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job, seed_job_prereqs
from apps.core.models import CompanyDefaults
from apps.timesheet.tests.conftest import make_staff, make_time_line

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

SUMMARY_URL = "/api/accounting/reports/staff-performance-summary/"
JUNE = {"start_date": "2026-06-01", "end_date": "2026-06-30"}
WORKDAY = date(2026, 6, 10)


def detail_url(staff_id: str) -> str:
    return f"/api/accounting/reports/staff-performance/{staff_id}/"


class TestStaffPerformanceSummary:
    def test_requires_authentication(self) -> None:
        assert Client().get(SUMMARY_URL, JUNE).status_code == 401

    def test_missing_dates_are_rejected(self, authenticated_client: Client) -> None:
        assert authenticated_client.get(SUMMARY_URL).status_code == 422

    def test_shop_company_time_is_never_billable(self, authenticated_client: Client) -> None:
        worker = make_staff("worker@example.com")
        client_co = make_company("Client Co")
        shop_co = CompanyDefaults.get_solo().shop_company
        client_job = make_job(client_co, worker)
        shop_job = make_job(shop_co, worker, name="Shop maintenance")

        # 6h billable client work at $120/h rev, $40/h cost.
        make_time_line(
            client_job,
            worker,
            accounting_date=WORKDAY,
            hours="6.000",
            unit_cost="40.00",
            unit_rev="120.00",
        )
        # 2h on the shop job — never billable (the model itself enforces
        # is_billable=False on shop-job time, so the flag is honest here).
        make_time_line(
            shop_job,
            worker,
            accounting_date=WORKDAY,
            hours="2.000",
            unit_cost="40.00",
            unit_rev="0.00",
            is_billable=False,
        )

        body = authenticated_client.get(SUMMARY_URL, JUNE).json()
        row = next(s for s in body["staff"] if s["staff_id"] == str(worker.id))
        assert row["total_hours"] == 8.0
        assert row["billable_hours"] == 6.0
        assert row["billable_percentage"] == 75.0
        assert row["total_revenue"] == 720.0
        assert row["total_cost"] == 320.0
        assert row["profit"] == 400.0
        assert row["revenue_per_hour"] == 90.0
        assert row["profit_per_hour"] == 50.0
        assert row["jobs_worked"] == 2
        # Summary rows carry no job breakdown (detail-only, as in v1).
        assert "job_breakdown" not in row

        assert body["period_summary"]["total_staff"] == 1
        assert body["team_averages"]["billable_percentage"] == 75.0

    def test_staff_without_hours_are_omitted(self, authenticated_client: Client) -> None:
        make_staff("idle@example.com")
        worker = make_staff("busy@example.com")
        company = make_company("Busy Co")
        job = make_job(company, worker)
        make_time_line(job, worker, accounting_date=WORKDAY, hours="4.000")

        body = authenticated_client.get(SUMMARY_URL, JUNE).json()
        ids = {s["staff_id"] for s in body["staff"]}
        assert ids == {str(worker.id)}


class TestStaffPerformanceDetail:
    def test_detail_includes_job_breakdown(self, authenticated_client: Client) -> None:
        worker = make_staff("detail@example.com")
        company = make_company("Detail Co")
        job = make_job(company, worker, name="Breakdown job")
        make_time_line(
            job,
            worker,
            accounting_date=WORKDAY,
            hours="3.000",
            unit_cost="40.00",
            unit_rev="120.00",
        )
        make_time_line(
            job,
            worker,
            accounting_date=WORKDAY,
            hours="1.000",
            unit_cost="40.00",
            unit_rev="0.00",
            is_billable=False,
        )

        body = authenticated_client.get(detail_url(str(worker.id)), JUNE).json()
        assert len(body["staff"]) == 1
        breakdown = body["staff"][0]["job_breakdown"]
        row = next(b for b in breakdown if b["job_id"] == str(job.id))
        assert row["billable_hours"] == 3.0
        assert row["non_billable_hours"] == 1.0
        assert row["total_hours"] == 4.0
        assert row["revenue"] == 360.0
        assert row["profit"] == 360.0 - 160.0
        assert row["revenue_per_hour"] == 90.0

    def test_unknown_staff_is_404(self, authenticated_client: Client) -> None:
        seed_job_prereqs()  # the report reads CompanyDefaults, as production always can
        response = authenticated_client.get(
            detail_url("00000000-0000-0000-0000-000000000000"), JUNE
        )
        assert response.status_code == 404
        # v1's specific message, not the generic route-miss "Not found."
        assert "No performance data found" in response.json()["detail"]
