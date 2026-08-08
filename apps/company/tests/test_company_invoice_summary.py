"""Invoice-summary annotation tests.

Company creation remains covered by ``test_company_api.TestCreate`` while the
accounting-provider write path is an explicit Phase 4 seam.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.company.models import Company, ContactMethod
from apps.company.services.company_rest_service import (
    CompanyRestService,
    _date_to_datetime,
)
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice

pytestmark = pytest.mark.django_db


def test_with_invoice_summary_sets_latest_invoice_date_and_total_spend() -> None:
    """Company search can mislead credit decisions if invoice rollups drift."""
    company = make_company("Acme")
    invoice_a = make_invoice(company, invoice_date=date(2024, 1, 10))
    invoice_a.total_excl_tax = Decimal("100.00")
    invoice_a.save(update_fields=["total_excl_tax"])
    invoice_b = make_invoice(company, invoice_date=date(2024, 2, 20))
    invoice_b.total_excl_tax = Decimal("25.50")
    invoice_b.save(update_fields=["total_excl_tax"])

    annotated = Company.objects.with_invoice_summary().get(id=company.id)

    assert annotated.last_invoice_date == date(2024, 2, 20)
    assert annotated.total_spend == Decimal("125.50")


def test_with_invoice_summary_handles_companies_without_invoices() -> None:
    """New companies must render as zero-spend, not error or stale data."""
    company = make_company("No Invoices")

    annotated = Company.objects.with_invoice_summary().get(id=company.id)

    assert annotated.last_invoice_date is None
    assert annotated.total_spend == Decimal("0.00")


def test_invoice_summary_properties_require_annotation() -> None:
    """Unannotated access must fail loudly instead of issuing hidden queries."""
    company = make_company("Unannotated")

    with pytest.raises(RuntimeError, match="with_invoice_summary"):
        _ = company.last_invoice_date

    with pytest.raises(RuntimeError, match="with_invoice_summary"):
        _ = company.total_spend


def test_formatting_annotated_companies_does_not_query_invoice_metrics() -> None:
    """Formatting search results must not reintroduce invoice N+1 queries."""
    with_invoices = make_company("With Invoices")
    without_invoices = make_company("Without Invoices")
    first = make_invoice(with_invoices, invoice_date=date(2024, 1, 1))
    first.total_excl_tax = Decimal("10.00")
    first.save(update_fields=["total_excl_tax"])
    second = make_invoice(with_invoices, invoice_date=date(2024, 1, 2))
    second.total_excl_tax = Decimal("5.25")
    second.save(update_fields=["total_excl_tax"])

    companies = list(
        Company.objects.with_invoice_summary()
        .annotate(phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk"))
        .filter(id__in=[with_invoices.id, without_invoices.id])
        .order_by("name")
    )

    with CaptureQueriesContext(connection) as captured:
        formatted = CompanyRestService._format_company_search_results(companies)

    assert len(captured) == 0
    assert formatted == [
        {
            "id": str(with_invoices.id),
            "name": "With Invoices",
            "email": "",
            "phone": "",
            "address": "",
            "is_account_customer": False,
            "is_supplier": False,
            "allow_jobs": True,
            "xero_contact_id": "",
            "last_invoice_date": _date_to_datetime(date(2024, 1, 2)),
            "total_spend": 15.25,
        },
        {
            "id": str(without_invoices.id),
            "name": "Without Invoices",
            "email": "",
            "phone": "",
            "address": "",
            "is_account_customer": False,
            "is_supplier": False,
            "allow_jobs": True,
            "xero_contact_id": "",
            "last_invoice_date": None,
            "total_spend": 0.0,
        },
    ]
