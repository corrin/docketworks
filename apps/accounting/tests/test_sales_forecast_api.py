"""Business-behaviour tests for the sales-forecast endpoints.

These tests pin month bucketing, the Xero-vs-JM variance, and the
matched/xero-only/jm-only row
classification.
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.test import Client

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

from apps.accounts.models import Staff
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job, make_material_line
from apps.job.models import Job

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

LIST_URL = "/api/accounting/reports/sales-forecast/"
JUNE_KEY = "2026-06"


def add_actual_line(job: Job, *, on: date, rev: str) -> object:
    return make_material_line(job, rev=rev, on=on)


class TestSalesForecastList:
    def test_requires_authentication(self) -> None:
        assert Client().get(LIST_URL).status_code == 401

    def test_months_compare_xero_invoices_with_jm_revenue(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Forecast Co")
        job = make_job(company, staff)
        add_actual_line(job, on=date(2026, 6, 15), rev="800.00")
        # AUTHORISED invoice counts at total_incl_tax; DRAFT is excluded here
        # (opposite of the WIP report — recorded v1 divergence).
        make_invoice(
            company,
            job=job,
            invoice_date=date(2026, 6, 20),
            status="AUTHORISED",
            total_excl_tax=Decimal("1000.00"),
        )
        make_invoice(
            company,
            job=job,
            invoice_date=date(2026, 6, 21),
            status="DRAFT",
            total_excl_tax=Decimal("9999.00"),
        )

        months = authenticated_client.get(LIST_URL).json()["months"]
        row = next(m for m in months if m["month"] == JUNE_KEY)
        assert row["month_label"] == "Jun 2026"
        assert row["xero_sales"] == 1150.0  # total_incl_tax of the AUTHORISED one
        assert row["jm_sales"] == 800.0
        assert row["variance"] == 350.0
        assert row["variance_pct"] == round(350.0 / 1150.0 * 100, 2)

    def test_months_before_app_adoption_are_hidden(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Old Co")
        job = make_job(company, staff)
        add_actual_line(job, on=date(2025, 3, 15), rev="500.00")  # pre-2025-04
        add_actual_line(job, on=date(2026, 6, 15), rev="100.00")

        months = [m["month"] for m in authenticated_client.get(LIST_URL).json()["months"]]
        assert "2025-03" not in months
        assert JUNE_KEY in months
        assert months == sorted(months, reverse=True)


class TestSalesForecastMonthDetail:
    def detail(self, client: Client, month: str) -> "_MonkeyPatchedWSGIResponse":
        return client.get(f"/api/accounting/reports/sales-forecast/{month}/")

    def test_rows_classify_matched_xero_only_and_jm_only(
        self, authenticated_client: Client, staff: Staff
    ) -> None:
        company = make_company("Detail Co")

        matched = make_job(company, staff, name="Matched job")
        add_actual_line(matched, on=date(2026, 6, 10), rev="700.00")
        make_invoice(
            company,
            job=matched,
            invoice_date=date(2026, 6, 12),
            status="PAID",
            total_excl_tax=Decimal("600.00"),
        )

        make_invoice(  # no job link -> xero_only
            company,
            invoice_date=date(2026, 6, 5),
            status="AUTHORISED",
            total_excl_tax=Decimal("200.00"),
        )

        jm_only = make_job(company, staff, name="Uninvoiced job")
        add_actual_line(jm_only, on=date(2026, 6, 18), rev="300.00")

        body = self.detail(authenticated_client, JUNE_KEY).json()
        assert body["month"] == JUNE_KEY
        assert body["month_label"] == "Jun 2026"
        rows = body["rows"]

        matched_row = next(r for r in rows if r["job_id"] == str(matched.id))
        assert matched_row["total_invoiced"] == 690.0  # incl tax
        assert matched_row["job_revenue"] == 700.0
        assert matched_row["variance"] == -10.0
        assert matched_row["total_xero_all_time"] == 690.0
        assert matched_row["total_jm_all_time"] == 700.0
        assert matched_row["variance_all_time"] == -10.0

        xero_only_row = next(r for r in rows if r["job_id"] is None)
        assert xero_only_row["note"] == "Xero only"
        assert xero_only_row["total_invoiced"] == 230.0
        assert xero_only_row["job_revenue"] == 0.0

        jm_only_row = next(r for r in rows if r["job_id"] == str(jm_only.id))
        assert jm_only_row["note"] == "JM only"
        assert jm_only_row["invoice_numbers"] is None
        assert jm_only_row["job_revenue"] == 300.0

    def test_malformed_or_preadoption_month_is_rejected(self, authenticated_client: Client) -> None:
        assert self.detail(authenticated_client, "junk").status_code == 422
        assert self.detail(authenticated_client, "2026-13").status_code == 422
        assert self.detail(authenticated_client, "2025-03").status_code == 422
