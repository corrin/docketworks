"""Business-behaviour tests for GET /api/accounting/reports/rdti-spend/.

Regression: ``rdti_type`` must accept the report's valid "unclassified" row
rather than applying the narrower model-choice validation and returning 500.
"""

from datetime import date

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job, make_material_line
from apps.job.models import Job

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

URL = "/api/accounting/reports/rdti-spend/"
JUNE = {"start_date": "2026-06-01", "end_date": "2026-06-30"}


def add_material_line(job: Job, *, on: date, rev: str = "300.00", cost: str = "100.00") -> object:
    return make_material_line(job, rev=rev, cost=cost, quantity="2", on=on)


class TestRDTISpend:
    def test_requires_authentication(self) -> None:
        assert Client().get(URL, JUNE).status_code == 401

    def test_groups_spend_by_job_and_rdti_category(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("RDTI Co")
        core = make_job(company, staff, name="Core R&D job")
        Job.objects.filter(pk=core.pk).untracked_update(rdti_type="core_rd")
        unclassified = make_job(company, staff, name="Plain job")
        add_material_line(core, on=date(2026, 6, 10), rev="300.00", cost="100.00")
        add_material_line(unclassified, on=date(2026, 6, 12), rev="50.00", cost="20.00")

        body = authenticated_client.get(URL, JUNE).json()

        core_row = next(j for j in body["jobs"] if j["job_id"] == str(core.id))
        assert core_row["rdti_type"] == "core_rd"
        assert core_row["hours"] == 2.0
        assert core_row["cost"] == 200.0  # 2 x 100
        assert core_row["revenue"] == 600.0

        # Every category is present even when empty; a NULL rdti_type lands in
        # "unclassified" (the row that made v1's serializer choke).
        by_type = {s["rdti_type"]: s for s in body["summary"]}
        assert set(by_type) == {"non_rd", "core_rd", "supporting_rd", "unclassified"}
        assert by_type["core_rd"]["job_count"] == 1
        assert by_type["unclassified"]["job_count"] == 1
        assert by_type["unclassified"]["cost"] == 40.0
        assert by_type["non_rd"]["job_count"] == 0

        assert body["totals"]["cost"] == 240.0
        assert body["totals"]["revenue"] == 700.0

    def test_lines_outside_range_are_excluded(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Range Co")
        job = make_job(company, staff)
        add_material_line(job, on=date(2026, 5, 31), rev="999.00")
        add_material_line(job, on=date(2026, 6, 15), rev="100.00")

        body = authenticated_client.get(URL, JUNE).json()
        row = next(j for j in body["jobs"] if j["job_id"] == str(job.id))
        assert row["revenue"] == 200.0  # only the June line (qty 2 x 100)

    def test_inverted_range_is_rejected(self, authenticated_client: Client) -> None:
        response = authenticated_client.get(
            URL, {"start_date": "2026-06-30", "end_date": "2026-06-01"}
        )
        assert response.status_code == 422
