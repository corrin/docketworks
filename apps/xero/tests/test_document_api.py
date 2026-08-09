"""The document-push HTTP surface: auth gates, lookups, status clamping.

Business risk covered: these endpoints are what the Finish tab drives during
the invoice E2E spec, but the spec exercises only the happy path — the auth
401, the 404s, the calc 400 whose text the dialog shows, and the clamp that
keeps live-Xero statuses (429/503) inside the declared response map are only
reachable here.
"""

import json
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.accounting.models import Invoice, Quote
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job, make_material_line
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder
from apps.xero.documents.invoice import XeroInvoiceManager
from apps.xero.documents.po import XeroPurchaseOrderManager
from apps.xero.models import XeroAccount

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

pytestmark = pytest.mark.django_db

TOKEN = {"access_token": "t"}


@pytest.fixture
def company() -> Company:
    return Company.objects.create(
        name="Document API Co",
        xero_contact_id=str(uuid.uuid4()),
        xero_last_modified=timezone.now(),
    )


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    new_job = make_job(company, office_staff, pricing_methodology="fixed_price")
    make_material_line(new_job, set_kind="quote", rev="1000.00", cost="0.00")
    return new_job


def _create_invoice(
    api: Client, job_id: object, body: dict[str, object]
) -> "_MonkeyPatchedWSGIResponse":
    return api.post(
        f"/api/xero/create_invoice/{job_id}",
        data=json.dumps(body),
        content_type="application/json",
    )


class TestCreateInvoiceEndpoint:
    def test_readonly_end_to_end_returns_201(self, api: Client, job: Job) -> None:
        """The full stack the E2E spec drives, minus the browser: endpoint →
        calc → manager → readonly fabrication → local row."""
        CompanyDefaults.objects.update(
            xero_sales_branding_theme_id=uuid.uuid4(), gst_rate=Decimal("0.1500")
        )
        CompanyDefaults.clear_cache()
        XeroAccount.objects.create(
            xero_id=uuid.uuid4(),
            account_code="200",
            account_name="Sales",
            xero_last_modified=timezone.now(),
            raw_json={},
        )

        with (
            override_settings(XERO_READONLY=True),
            patch("apps.xero.api.get_valid_token", return_value=TOKEN),
            patch.object(XeroInvoiceManager, "_attach_workshop_pdf", return_value=None),
        ):
            response = _create_invoice(api, job.id, {"mode": "invoice_full"})

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["success"] is True
        assert float(body["total_excl_tax"]) == 1000.00
        invoice = job.invoices.get()
        assert invoice.number.startswith("INV-E2E-")
        job.refresh_from_db()
        assert job.fully_invoiced

    def test_no_token_is_401(self, api: Client, job: Job) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=None):
            response = _create_invoice(api, job.id, {"mode": "invoice_full"})
        assert response.status_code == 401
        assert response.json()["redirect_to_auth"] is True

    def test_unknown_job_is_404(self, api: Client) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = _create_invoice(api, uuid.uuid4(), {"mode": "invoice_full"})
        assert response.status_code == 404

    def test_calc_error_is_400_with_the_reason(self, api: Client, job: Job) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = _create_invoice(api, job.id, {"mode": "invoice_percent"})
        assert response.status_code == 400
        assert "percent is required" in response.json()["error"]

    def test_provider_status_is_clamped_to_the_declared_map(self, api: Client, job: Job) -> None:
        """A live-Xero 429 must come back as the declared 400 payload, not a
        ConfigError-turned-500."""
        with (
            patch("apps.xero.api.get_valid_token", return_value=TOKEN),
            patch.object(
                XeroInvoiceManager,
                "create_document",
                return_value={
                    "success": False,
                    "error": "Rate limit exceeded",
                    "status": 429,
                },
            ),
        ):
            response = _create_invoice(api, job.id, {"mode": "invoice_full"})

        assert response.status_code == 400
        assert response.json()["error"] == "Rate limit exceeded"

    def test_job_without_company_is_400(self, api: Client, office_staff: Staff) -> None:
        orphan_company = Company.objects.create(
            name="Detached Co", xero_last_modified=timezone.now()
        )
        orphan = make_job(orphan_company, office_staff, pricing_methodology="fixed_price")
        make_material_line(orphan, set_kind="quote", rev="10.00", cost="0.00")
        Job.objects.filter(pk=orphan.pk).untracked_update(company=None)
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = _create_invoice(api, orphan.id, {"mode": "invoice_full"})
        assert response.status_code == 400
        assert "client company" in response.json()["error"]


class TestDeleteInvoiceEndpoint:
    def test_readonly_delete_removes_local_row(self, api: Client, job: Job) -> None:
        xero_id = uuid.uuid4()
        assert job.company is not None  # the fixture always sets a company
        Invoice.objects.create(
            xero_id=xero_id,
            number="INV-E2E-DEAD",
            company=job.company,
            job=job,
            date="2026-08-09",
            status="SUBMITTED",
            total_excl_tax=Decimal("100"),
            tax=Decimal("15"),
            total_incl_tax=Decimal("115"),
            amount_due=Decimal("115"),
            xero_last_modified=timezone.now(),
            raw_json={},
        )

        with (
            override_settings(XERO_READONLY=True),
            patch("apps.xero.api.get_valid_token", return_value=TOKEN),
        ):
            response = api.delete(f"/api/xero/delete_invoice/{job.id}?xero_invoice_id={xero_id}")

        assert response.status_code == 200, response.content
        assert not Invoice.objects.filter(xero_id=xero_id).exists()

    def test_unknown_invoice_is_404(self, api: Client, job: Job) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = api.delete(
                f"/api/xero/delete_invoice/{job.id}?xero_invoice_id={uuid.uuid4()}"
            )
        assert response.status_code == 404


def _create_quote(
    api: Client, job_id: object, body: dict[str, object]
) -> "_MonkeyPatchedWSGIResponse":
    return api.post(
        f"/api/xero/create_quote/{job_id}",
        data=json.dumps(body),
        content_type="application/json",
    )


def _quote_sales_config() -> None:
    CompanyDefaults.objects.update(
        xero_sales_branding_theme_id=uuid.uuid4(),
        xero_quote_terms="Terms of trade can be found on our website.",
        gst_rate=Decimal("0.1500"),
    )
    CompanyDefaults.clear_cache()
    XeroAccount.objects.create(
        xero_id=uuid.uuid4(),
        account_code="200",
        account_name="Sales",
        xero_last_modified=timezone.now(),
        raw_json={},
    )


class TestCreateQuoteEndpoint:
    def test_readonly_end_to_end_returns_201(self, api: Client, job: Job) -> None:
        """The full stack the E2E spec drives, minus the browser: endpoint →
        manager → readonly fabrication → local Quote row."""
        _quote_sales_config()

        with (
            override_settings(XERO_READONLY=True),
            patch("apps.xero.api.get_valid_token", return_value=TOKEN),
        ):
            response = _create_quote(api, job.id, {"breakdown": False})

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["success"] is True
        assert float(body["total_excl_tax"]) == 1000.00
        quote = Quote.objects.get(job=job)
        assert quote.number is not None and quote.number.startswith("QU-E2E-")
        assert body["xero_id"] == str(quote.xero_id)
        assert body["quote_id"] == str(quote.id)

    def test_no_token_is_401(self, api: Client, job: Job) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=None):
            response = _create_quote(api, job.id, {"breakdown": False})
        assert response.status_code == 401
        assert response.json()["redirect_to_auth"] is True

    def test_unknown_job_is_404(self, api: Client) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = _create_quote(api, uuid.uuid4(), {"breakdown": False})
        assert response.status_code == 404

    def test_missing_breakdown_is_422(self, api: Client, job: Job) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = _create_quote(api, job.id, {})
        assert response.status_code == 422

    def test_business_refusal_is_400_with_the_reason(self, api: Client, job: Job) -> None:
        """A T&M job's refusal text reaches the dialog unchanged."""
        _quote_sales_config()
        Job.objects.filter(pk=job.pk).untracked_update(pricing_methodology="time_materials")

        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = _create_quote(api, job.id, {"breakdown": False})

        assert response.status_code == 400
        body = response.json()
        assert "time and materials" in body["error"]
        assert body["error_type"] == "validation_error"

    def test_provider_status_is_clamped_to_the_declared_map(self, api: Client, job: Job) -> None:
        from apps.xero.documents.quote import XeroQuoteManager  # noqa: PLC0415

        with (
            patch("apps.xero.api.get_valid_token", return_value=TOKEN),
            patch.object(
                XeroQuoteManager,
                "create_document",
                return_value={
                    "success": False,
                    "error": "Rate limit exceeded",
                    "status": 429,
                },
            ),
        ):
            response = _create_quote(api, job.id, {"breakdown": False})

        assert response.status_code == 400
        assert response.json()["error"] == "Rate limit exceeded"

    def test_job_without_company_is_400(self, api: Client, office_staff: Staff) -> None:
        orphan_company = Company.objects.create(
            name="Detached Quote Co", xero_last_modified=timezone.now()
        )
        orphan = make_job(orphan_company, office_staff, pricing_methodology="fixed_price")
        make_material_line(orphan, set_kind="quote", rev="10.00", cost="0.00")
        Job.objects.filter(pk=orphan.pk).untracked_update(company=None)
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = _create_quote(api, orphan.id, {"breakdown": False})
        assert response.status_code == 400
        assert "client company" in response.json()["error"]


class TestDeleteQuoteEndpoint:
    def test_readonly_delete_removes_local_row(self, api: Client, job: Job) -> None:
        assert job.company is not None  # the fixture always sets a company
        Quote.objects.create(
            xero_id=uuid.uuid4(),
            number="QU-E2E-DEAD",
            company=job.company,
            job=job,
            date="2026-08-09",
            total_excl_tax=Decimal("100"),
            total_incl_tax=Decimal("115"),
        )

        with (
            override_settings(XERO_READONLY=True),
            patch("apps.xero.api.get_valid_token", return_value=TOKEN),
        ):
            response = api.delete(f"/api/xero/delete_quote/{job.id}")

        assert response.status_code == 200, response.content
        assert response.json()["message"] == "Quote deleted successfully."
        assert not Quote.objects.filter(job=job).exists()

    def test_job_without_quote_is_400(self, api: Client, job: Job) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = api.delete(f"/api/xero/delete_quote/{job.id}")
        assert response.status_code == 400
        assert "no Xero quote" in response.json()["error"]

    def test_unknown_job_is_404(self, api: Client) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=TOKEN):
            response = api.delete(f"/api/xero/delete_quote/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_no_token_is_401(self, api: Client, job: Job) -> None:
        with patch("apps.xero.api.get_valid_token", return_value=None):
            response = api.delete(f"/api/xero/delete_quote/{job.id}")
        assert response.status_code == 401


class TestPurchaseOrderEndpointClamp:
    def test_manager_429_is_clamped(self, api: Client, company: Company) -> None:
        po = PurchaseOrder.objects.create(supplier=company, po_number="PO-API-1")
        with (
            patch("apps.xero.api.get_valid_token", return_value=TOKEN),
            patch.object(
                XeroPurchaseOrderManager,
                "sync_to_xero",
                return_value={
                    "success": False,
                    "error": "Rate limit exceeded",
                    "error_type": "api_error",
                    "status": 429,
                },
            ),
        ):
            response = api.post(f"/api/xero/create_purchase_order/{po.id}")

        assert response.status_code == 400
        assert response.json()["error"] == "Rate limit exceeded"
