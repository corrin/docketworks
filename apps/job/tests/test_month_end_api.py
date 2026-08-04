"""API tests for the month-end endpoints (v1 month_end_rest_view + month_end_service).

First coverage for this surface — v1 shipped it with zero tests. Pins the GET
wire shape (special jobs with their prior actual cost sets, the stock job with
per-cost-set material totals) and the POST semantics: each selected job gets a
NEW empty "actual" cost set as latest — nothing is archived, the previous cost
sets simply become history.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate
from apps.company.tests.job_fixtures import seed_job_prereqs
from apps.core.models import AppError
from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet
from apps.purchasing.models import Stock

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.job.tests.urls"),
]


@pytest.fixture(autouse=True)
def _reset_stock_holding_cache() -> None:
    """Stock caches the stock-holding job on the class; tests get fresh rows."""
    Stock._stock_holding_job = None


@pytest.fixture
def stock_job(company: Company, office_staff: Staff) -> Job:
    """The job Stock.get_stock_holding_job() resolves to (special status, as in prod)."""
    seed_job_prereqs()
    job = Job(name=Stock.STOCK_HOLDING_JOB_NAME, company=company, status="special")
    job.save(staff=office_staff)
    return job


def _special_job(company: Company, staff: Staff, name: str) -> Job:
    seed_job_prereqs()
    job = Job(name=name, company=company, status="special")
    job.save(staff=staff)
    return job


def _set_actual_summary(job: Job, summary: dict[str, float]) -> CostSet:
    """Overwrite the latest actual cost set's summary directly."""
    actual = job.cost_sets.get(kind="actual", id=job.latest_actual_id)
    actual.summary = summary
    actual.save()
    return actual


def _roll_actual(job: Job, staff: Staff, summary: dict[str, float]) -> CostSet:
    """Open a new latest 'actual' cost set, pushing the previous one into history."""
    rev = job.cost_sets.filter(kind="actual").count() + 1
    cost_set = CostSet.objects.create(job=job, kind="actual", rev=rev, summary=summary)
    job.set_latest("actual", cost_set, staff)
    return cost_set


def _material_line(cost_set: CostSet, quantity: str, unit_cost: str) -> CostLine:
    return CostLine.objects.create(
        cost_set=cost_set,
        kind="material",
        desc="Stock material",
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        unit_rev=Decimal("0.00"),
        accounting_date=timezone.localdate(),
    )


class TestMonthEndGet:
    @pytest.mark.usefixtures("stock_job")
    def test_lists_special_jobs_with_history_and_latest_totals(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        """GET reports special jobs only; totals come from the LATEST actual
        cost set, history from the prior ones (latest excluded)."""
        special = _special_job(company, office_staff, "Shop Cleanup")
        older = _set_actual_summary(special, {"cost": 100.5, "rev": 0, "hours": 5.25})
        _roll_actual(special, office_staff, {"cost": 40.0, "rev": 0, "hours": 2.0})
        make_ordinary = Job(name="Ordinary Job", company=company, status="in_progress")
        make_ordinary.save(staff=office_staff)

        response = client.get("/api/job/month-end/")

        assert response.status_code == 200
        payload = response.json()
        assert [job["job_id"] for job in payload["jobs"]] == [str(special.id)]
        job_payload = payload["jobs"][0]
        assert job_payload["job_number"] == special.job_number
        assert job_payload["job_name"] == "Shop Cleanup"
        assert job_payload["company_name"] == company.name
        assert job_payload["total_hours"] == 2.0
        assert job_payload["total_dollars"] == 40.0
        assert job_payload["history"] == [
            {
                "date": older.created.date().isoformat(),
                "total_hours": 5.25,
                "total_dollars": 100.5,
            }
        ]

    def test_stock_job_reports_material_totals_for_every_actual_cost_set(
        self, client: Client, office_staff: Staff, stock_job: Job
    ) -> None:
        """Stock history covers ALL actual cost sets (latest included) and
        counts/sums only material lines; the stock job never appears in
        ``jobs`` even though its status is special."""
        first_actual = stock_job.cost_sets.get(kind="actual", id=stock_job.latest_actual_id)
        _material_line(first_actual, "2.000", "10.00")
        _material_line(first_actual, "1.000", "5.50")
        CostLine.objects.create(
            cost_set=first_actual,
            kind="adjust",
            desc="Not material",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("99.00"),
            unit_rev=Decimal("0.00"),
            accounting_date=timezone.localdate(),
        )
        second_actual = _roll_actual(stock_job, office_staff, {"cost": 0, "rev": 0, "hours": 0})

        response = client.get("/api/job/month-end/")

        assert response.status_code == 200
        payload = response.json()
        assert payload["jobs"] == []
        stock_payload = payload["stock_job"]
        assert stock_payload["job_id"] == str(stock_job.id)
        assert stock_payload["job_number"] == stock_job.job_number
        assert stock_payload["job_name"] == Stock.STOCK_HOLDING_JOB_NAME
        assert stock_payload["history"] == [
            {
                "date": first_actual.created.date().isoformat(),
                "material_line_count": 2,
                "material_cost": 25.5,
            },
            {
                "date": second_actual.created.date().isoformat(),
                "material_line_count": 0,
                "material_cost": 0.0,
            },
        ]


class TestMonthEndPost:
    def test_rolls_a_new_empty_actual_cost_set(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        """POST opens a fresh empty 'actual' rev as latest; the previous cost
        set survives untouched (v1 rolled the period forward, no archiving)."""
        special = _special_job(company, office_staff, "Shop Cleanup")
        previous = _set_actual_summary(special, {"cost": 100.5, "rev": 0, "hours": 5.25})

        response = client.post(
            "/api/job/month-end/",
            data={"job_ids": [str(special.id)]},
            content_type="application/json",
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["processed"] == [str(special.id)]
        assert payload["errors"] == []

        special.refresh_from_db()
        actuals = list(special.cost_sets.filter(kind="actual").order_by("rev"))
        assert len(actuals) == 2
        latest = actuals[-1]
        assert special.latest_actual_id == latest.id
        assert latest.rev == 2
        assert latest.summary == {"cost": 0, "rev": 0, "hours": 0}
        previous.refresh_from_db()
        assert previous.summary == {"cost": 100.5, "rev": 0, "hours": 5.25}
        assert special.status == "special"

    def test_unknown_job_id_is_reported_not_fatal(
        self, client: Client, company: Company, office_staff: Staff
    ) -> None:
        """A failing id lands in ``errors`` (and persists an AppError) while
        the rest of the batch still processes."""
        special = _special_job(company, office_staff, "Shop Cleanup")
        unknown_id = uuid4()

        response = client.post(
            "/api/job/month-end/",
            data={"job_ids": [str(unknown_id), str(special.id)]},
            content_type="application/json",
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["processed"] == [str(special.id)]
        assert len(payload["errors"]) == 1
        assert str(unknown_id) in payload["errors"][0]
        assert AppError.objects.count() == 1


class TestMonthEndAuth:
    """Auth rejects before the handler runs, so no stock job is needed."""

    def test_get_requires_authentication(self) -> None:
        assert Client().get("/api/job/month-end/").status_code == 401

    def test_post_requires_authentication(self) -> None:
        response = Client().post(
            "/api/job/month-end/", data={"job_ids": []}, content_type="application/json"
        )
        assert response.status_code == 401

    def test_get_rejects_workshop_staff(self, workshop_staff: Staff) -> None:
        workshop_client = Client()
        authenticate(workshop_client, workshop_staff)
        assert workshop_client.get("/api/job/month-end/").status_code == 403

    def test_post_rejects_workshop_staff(self, workshop_staff: Staff) -> None:
        workshop_client = Client()
        authenticate(workshop_client, workshop_staff)
        response = workshop_client.post(
            "/api/job/month-end/", data={"job_ids": []}, content_type="application/json"
        )
        assert response.status_code == 403
