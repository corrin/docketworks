"""Business-behaviour tests for GET /api/accounting/reports/wip/.

v1 had no tests for WIPService; these pin the calculations that matter:
net WIP = valued work minus invoiced, the report-date cutoff, and the
no-work-status exclusions (ADR 0025).
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.tests.conftest import make_time_line

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

URL = "/api/accounting/reports/wip/"


def make_wip_job(company: Company, staff: Staff, *, name: str = "WIP job") -> Job:
    """A job in a status WIP counts (new jobs default to draft, which it excludes)."""
    job = make_job(company, staff, name=name)
    job.status = "in_progress"
    job.save(staff=staff)
    return job


def add_actual_line(
    job: Job,
    *,
    kind: str = "material",
    rev: str = "500.00",
    cost: str = "200.00",
    days_ago: int = 0,
) -> CostLine:
    """A material/adjust actual line (time lines carry staff+pay-item constraints
    — use make_time_line for those)."""
    return CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind=kind,
        desc=f"{kind} work",
        quantity=Decimal("1"),
        unit_cost=Decimal(cost),
        unit_rev=Decimal(rev),
        accounting_date=timezone.localdate() - timedelta(days=days_ago),
    )


class TestWIPReport:
    def test_requires_authentication(self) -> None:
        assert Client().get(URL).status_code == 401

    def test_net_wip_is_revenue_minus_invoiced(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("WIP Co")
        job = make_wip_job(company, staff)
        make_time_line(
            job,
            staff,
            accounting_date=timezone.localdate(),
            hours="1.000",
            unit_cost="200.00",
            unit_rev="500.00",
        )
        add_actual_line(job, kind="material", rev="300.00", cost="100.00")
        make_invoice(company, job=job, status="AUTHORISED", total_excl_tax=Decimal("250.00"))

        body = authenticated_client.get(URL).json()
        row = next(r for r in body["jobs"] if r["job_number"] == job.job_number)
        assert row["total_rev"] == 800.0
        assert row["total_cost"] == 300.0
        assert row["time_rev"] == 500.0
        assert row["material_rev"] == 300.0
        assert row["invoiced"] == 250.0
        assert row["gross_wip"] == 800.0  # method defaults to revenue
        assert row["net_wip"] == 550.0
        assert body["method"] == "revenue"
        summary = body["summary"]
        assert summary["job_count"] == 1
        assert summary["total_net"] == 550.0
        assert summary["by_status"][0]["status"] == job.status

    def test_cost_method_values_work_at_internal_cost(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Cost Co")
        job = make_wip_job(company, staff)
        add_actual_line(job, rev="500.00", cost="200.00")

        body = authenticated_client.get(URL, {"method": "cost"}).json()
        row = next(r for r in body["jobs"] if r["job_number"] == job.job_number)
        assert row["gross_wip"] == 200.0
        assert body["method"] == "cost"

    def test_lines_after_report_date_are_excluded(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Cutoff Co")
        job = make_wip_job(company, staff)
        add_actual_line(job, rev="100.00", days_ago=10)
        add_actual_line(job, rev="900.00", days_ago=0)

        as_at = (timezone.localdate() - timedelta(days=5)).isoformat()
        body = authenticated_client.get(URL, {"date": as_at}).json()
        row = next(r for r in body["jobs"] if r["job_number"] == job.job_number)
        assert row["total_rev"] == 100.0
        assert body["report_date"] == as_at

    def test_draft_and_fully_invoiced_jobs_are_not_wip(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Excluded Co")
        draft = make_job(company, staff, name="Draft job")  # default status draft
        add_actual_line(draft, rev="100.00")

        invoiced = make_wip_job(company, staff, name="Done job")
        add_actual_line(invoiced, rev="100.00")
        Job.objects.filter(pk=invoiced.pk).untracked_update(fully_invoiced=True)

        numbers = {r["job_number"] for r in authenticated_client.get(URL).json()["jobs"]}
        assert draft.job_number not in numbers
        assert invoiced.job_number not in numbers

    def test_zero_revenue_jobs_are_omitted(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Zero Co")
        job = make_wip_job(company, staff)

        numbers = {r["job_number"] for r in authenticated_client.get(URL).json()["jobs"]}
        assert job.job_number not in numbers
