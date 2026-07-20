import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounting.models import Invoice
from apps.company.models import Company, ContactMethod
from apps.company.services.company_rest_service import CompanyRestService
from apps.company.utils import date_to_datetime
from apps.company.views.company_rest_views import CompanyCreateRestView
from apps.testing import BaseTestCase
from apps.workflow.accounting.types import ContactResult


def _make_company(name: str) -> Company:
    return Company.objects.create(name=name, xero_last_modified=timezone.now())


def _make_invoice(company: Company, invoice_date: date, amount: Decimal) -> Invoice:
    return Invoice.objects.create(
        xero_id=uuid.uuid4(),
        number=f"INV-{uuid.uuid4().hex[:8]}",
        company=company,
        date=invoice_date,
        total_excl_tax=amount,
        tax=Decimal("0.00"),
        total_incl_tax=amount,
        amount_due=Decimal("0.00"),
        xero_last_modified=timezone.now(),
        raw_json={},
    )


def test_with_invoice_summary_sets_latest_invoice_date_and_total_spend(db):
    """Company search can mislead credit decisions if invoice rollups drift.

    This catches aggregation changes that sum only one invoice or choose the
    wrong date by using two invoices where the latest date and total differ.
    """
    company = _make_company("Acme")
    _make_invoice(company, date(2024, 1, 10), Decimal("100.00"))
    _make_invoice(company, date(2024, 2, 20), Decimal("25.50"))

    annotated = Company.objects.with_invoice_summary().get(id=company.id)

    assert annotated.last_invoice_date == date(2024, 2, 20)
    assert annotated.total_spend == Decimal("125.50")


def test_with_invoice_summary_handles_companies_without_invoices(db):
    """New companies must render as zero-spend, not error or stale data.

    This catches annotation changes that leave null totals for the frontend to
    format or accidentally join another company's invoice summary.
    """
    company = _make_company("No Invoices")

    annotated = Company.objects.with_invoice_summary().get(id=company.id)

    assert annotated.last_invoice_date is None
    assert annotated.total_spend == Decimal("0.00")


def test_invoice_summary_properties_require_annotation(db):
    """Unannotated access must fail loudly instead of issuing hidden queries.

    This catches callers bypassing ``with_invoice_summary`` and reintroducing
    per-company invoice lookups in list/search responses.
    """
    company = _make_company("Unannotated")

    with pytest.raises(RuntimeError, match="with_invoice_summary"):
        _ = company.last_invoice_date

    with pytest.raises(RuntimeError, match="with_invoice_summary"):
        _ = company.total_spend


def test_formatting_annotated_companies_does_not_query_invoice_metrics(db):
    """Formatting search results must not reintroduce invoice N+1 queries.

    This catches a formatter refactor that reads invoice relations/properties
    per row by asserting all invoice-derived values come from annotations.
    """
    with_invoices = _make_company("With Invoices")
    without_invoices = _make_company("Without Invoices")
    _make_invoice(with_invoices, date(2024, 1, 1), Decimal("10.00"))
    _make_invoice(with_invoices, date(2024, 1, 2), Decimal("5.25"))

    companies = list(
        Company.objects.with_invoice_summary()
        .annotate(
            phone=ContactMethod.primary_phone_annotation(
                owner="company", outer_ref="pk"
            )
        )
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
            "last_invoice_date": date_to_datetime(date(2024, 1, 2)),
            "total_spend": "$15.25",
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
            "total_spend": "$0.00",
        },
    ]


class CompanyCreateInvoiceSummaryTests(BaseTestCase):
    def test_create_company_response_formats_annotated_invoice_summary(self):
        """Create responses must match the company-search summary contract.

        This catches a view refactor that returns a raw Company payload without
        annotated invoice defaults, which would break newly-created company rows
        in the frontend.
        """
        provider = MagicMock()
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.search_contact_by_name.return_value = None
        provider.create_contact.return_value = ContactResult(
            success=True,
            external_id="xero-contact-id",
            name="New Company",
        )

        request = APIRequestFactory().post(
            "/api/companies/create/",
            {
                "name": "New Company",
                "email": "new@example.test",
                "address": "",
                "is_account_customer": True,
            },
            format="json",
        )
        force_authenticate(request, user=self.test_staff)

        with patch(
            "apps.company.services.company_rest_service.get_provider",
            return_value=provider,
        ):
            response = CompanyCreateRestView.as_view()(request)

        assert response.status_code == 201
        assert response.data["company"]["name"] == "New Company"
        assert response.data["company"]["last_invoice_date"] is None
        assert response.data["company"]["total_spend"] == "$0.00"

    def test_create_company_cleans_up_local_row_when_xero_create_fails(self):
        """Failed Xero contact creation must not leave a half-created company."""
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.search_contact_by_name.return_value = None
        provider.create_contact.return_value = ContactResult(
            success=False,
            error="RemoteDisconnected",
        )

        with patch(
            "apps.company.services.company_rest_service.get_provider",
            return_value=provider,
        ):
            with pytest.raises(ValueError, match="RemoteDisconnected"):
                CompanyRestService.create_company(
                    {
                        "name": "Failed Xero Company",
                        "email": "failed@example.test",
                        "address": "",
                        "is_account_customer": True,
                    }
                )

        assert not Company.objects.filter(name="Failed Xero Company").exists()
