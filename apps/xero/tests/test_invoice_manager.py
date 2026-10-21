"""The invoice push path: error contract, local persistence, readonly fabrication.

Business risks covered: an unexpected provider failure must reach the endpoint
as a raised, persisted exception (never a success-shaped dict); the local
Invoice mirror row must store the provider's canonical raw payload and totals;
and under XERO_READONLY the whole create path must produce the same local
effects with nothing reaching the tenant — that fabrication is what the E2E
invoice spec's balance assertions stand on.
"""

import uuid
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.accounting.models import Invoice
from apps.accounting.types import INVOICE_APPROVED, DocumentResult
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_invoice, make_material_line
from apps.core.errors import app_error_for, persist_app_error
from apps.core.models import AppError, CompanyDefaults
from apps.job.models import Job, JobEvent
from apps.xero.documents.invoice import XeroInvoiceManager
from apps.xero.models import XeroAccount

pytestmark = pytest.mark.django_db

THEME_ID = "11111111-2222-3333-4444-555555555555"

# The minimal audit trail the endpoint always supplies; create_document
# validates it before anything reaches the provider.
METADATA = {
    "mode": "invoice_full",
    "target_basis": "quote",
    "target_total": "100.00",
    "prior_invoiced_total": "0.00",
    "calculated_amount": "100.00",
}


@pytest.fixture(autouse=True)
def _sales_theme() -> None:
    """Sales documents stop at the config guard without a branding theme."""
    defaults = CompanyDefaults.get_solo()
    CompanyDefaults.objects.filter(pk=defaults.pk).update(
        xero_sales_branding_theme_id=uuid.UUID(THEME_ID),
        xero_quote_terms="Client-approved quote terms",
    )
    CompanyDefaults.clear_cache()


@pytest.fixture
def company() -> Company:
    return Company.objects.create(
        name="Invoice Manager Co",
        xero_contact_id=str(uuid.uuid4()),
        xero_tenant_id="test-tenant",
        xero_last_modified=timezone.now(),
    )


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    new_job = Job(company=company, name="Invoice Manager Job", pricing_methodology="fixed_price")
    new_job.save(staff=office_staff)
    return new_job


def _manager(company: Company, job: Job, staff: Staff, provider: Mock) -> XeroInvoiceManager:
    with patch("apps.xero.documents.base.get_provider", return_value=provider):
        return XeroInvoiceManager(company=company, job=job, staff=staff)


def _success_result(raw: dict[str, object] | None = None) -> DocumentResult:
    external_id = str(uuid.uuid4())
    return DocumentResult(
        success=True,
        external_id=external_id,
        number="INV-RAW-1",
        online_url=f"https://go.xero.com/app/invoicing/edit/{external_id}",
        raw_response=raw
        or {
            "_contact": {"_name": "Invoice Manager Co"},
            "_invoice_id": external_id,
            "_invoice_number": "INV-RAW-1",
            "_sub_total": "100.00",
            "_total_tax": "15.00",
            "_total": "115.00",
            "_amount_due": "115.00",
        },
    )


class TestErrorContract:
    """Unexpected provider failures re-raise once; they never become a dict."""

    def test_create_reraises_and_persists_once(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_invoice.side_effect = RuntimeError("Xero exploded")
        manager = _manager(company, job, office_staff, provider)

        with pytest.raises(RuntimeError, match="Xero exploded") as caught:
            manager.create_document(total_amount=Decimal("100"), billing_metadata=dict(METADATA))

        assert app_error_for(caught.value) is not None
        assert AppError.objects.count() == 1

    def test_delete_reraises_and_persists_once(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        provider.delete_invoice.side_effect = RuntimeError("Xero exploded")
        manager = _manager(company, job, office_staff, provider)
        draft = make_invoice(company, job=job, status="DRAFT")

        with (
            patch.object(XeroInvoiceManager, "get_xero_id", return_value=str(draft.xero_id)),
            pytest.raises(RuntimeError) as caught,
        ):
            manager.delete_document(void_approved=False)

        assert app_error_for(caught.value) is not None
        assert AppError.objects.count() == 1

    def test_delete_does_not_double_persist(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """The v1 delete path once lacked the pass-through arm and re-persisted."""
        original = RuntimeError("Persisted upstream")
        upstream_error = persist_app_error(original)

        provider = Mock()
        provider.delete_invoice.side_effect = original
        manager = _manager(company, job, office_staff, provider)
        draft = make_invoice(company, job=job, status="DRAFT")

        with (
            patch.object(XeroInvoiceManager, "get_xero_id", return_value=str(draft.xero_id)),
            pytest.raises(RuntimeError) as caught,
        ):
            manager.delete_document(void_approved=False)

        assert caught.value is original
        assert app_error_for(caught.value) == upstream_error
        assert AppError.objects.count() == 1

    def test_expected_provider_failure_returns_dict(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """A declined Xero call is a business outcome, not an exception."""
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_invoice.return_value = DocumentResult(
            success=False, error="Contact is archived", status_code=400
        )
        manager = _manager(company, job, office_staff, provider)

        result = manager.create_document(
            total_amount=Decimal("100"), billing_metadata=dict(METADATA)
        )

        assert not result["success"]
        assert result["status"] == 400
        assert AppError.objects.count() == 0

    def test_missing_branding_theme_is_a_configuration_error(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        CompanyDefaults.objects.update(xero_sales_branding_theme_id=None)
        CompanyDefaults.clear_cache()
        provider = Mock()
        manager = _manager(company, job, office_staff, provider)

        result = manager.create_document(
            total_amount=Decimal("100"), billing_metadata=dict(METADATA)
        )

        assert not result["success"]
        assert result["error_type"] == "configuration_error"
        assert result["status"] == 400
        provider.create_invoice.assert_not_called()


class TestLocalPersistence:
    def test_created_invoice_stores_canonical_raw_json_and_totals(
        self, company: Company, job: Job, office_staff: Staff, xero_tenant_id: str
    ) -> None:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_invoice.return_value = _success_result()
        provider.attach_file_to_invoice.return_value = True
        manager = _manager(company, job, office_staff, provider)

        with patch.object(XeroInvoiceManager, "_attach_workshop_pdf", return_value=None):
            result = manager.create_document(
                total_amount=Decimal("100.00"),
                billing_metadata={
                    "mode": "invoice_full",
                    "target_basis": "quote",
                    "target_total": "100.00",
                    "prior_invoiced_total": "0.00",
                    "calculated_amount": "100.00",
                },
            )

        assert result["success"]
        invoice = job.invoices.get()
        # The tenant is written with the id, never separately: an id with no
        # tenant cannot be attributed to an org.
        assert invoice.xero_tenant_id == xero_tenant_id
        assert isinstance(invoice.raw_json, dict)
        assert invoice.raw_json["_contact"]["_name"] == "Invoice Manager Co"
        assert "full" not in invoice.raw_json
        assert invoice.total_excl_tax == Decimal("100.00")
        assert invoice.tax == Decimal("15.00")
        assert invoice.total_incl_tax == Decimal("115.00")
        assert invoice.amount_due == Decimal("115.00")
        assert invoice.billing_metadata["mode"] == "invoice_full"
        event = JobEvent.objects.get(job=job, event_type="invoice_created")
        assert event.detail["xero_invoice_number"] == "INV-RAW-1"
        assert event.detail["remaining_to_invoice"] == "0.00"


class TestReadonlyFabrication:
    """The registry-selected readonly provider makes the whole path work
    without a tenant: fake id/number/totals, real local row, real recalc."""

    def test_create_document_lands_local_invoice_with_fake_totals(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        CompanyDefaults.objects.update(gst_rate=Decimal("0.1500"))
        CompanyDefaults.clear_cache()
        # The readonly provider still resolves the Sales account code from the
        # real chart-of-accounts mirror — reads stay live under XERO_READONLY.
        XeroAccount.objects.create(
            xero_id=uuid.uuid4(),
            account_code="200",
            account_name="Sales",
            xero_last_modified=timezone.now(),
            raw_json={},
        )
        # A quote worth exactly the invoiced amount: the same-request recalc
        # must flip fully_invoiced, which is what the E2E spec asserts.
        make_material_line(job, set_kind="quote", rev="1000.00", cost="0.00")

        with (
            override_settings(XERO_READONLY=True),
            patch.object(XeroInvoiceManager, "_attach_workshop_pdf", return_value=None),
        ):
            manager = XeroInvoiceManager(company=company, job=job, staff=office_staff)
            assert type(manager.provider).__name__ == "XeroReadOnlyProvider"
            result = manager.create_document(
                total_amount=Decimal("1000.00"),
                billing_metadata={
                    "mode": "invoice_full",
                    "target_basis": "quote",
                    "target_total": "1000.00",
                    "prior_invoiced_total": "0.00",
                    "calculated_amount": "1000.00",
                },
            )

        assert result["success"]
        invoice = job.invoices.get()
        assert invoice.number.startswith("INV-E2E-")
        assert invoice.total_excl_tax == Decimal("1000.00")
        assert invoice.tax == Decimal("150.00")
        assert invoice.total_incl_tax == Decimal("1150.00")
        assert invoice.raw_json["_e2e_stub"] is True
        # The same-request recalc the E2E fully-invoiced assertion stands on.
        job.refresh_from_db()
        assert job.fully_invoiced is True


def _delete(
    manager: XeroInvoiceManager, invoice: Invoice, *, void_approved: bool
) -> dict[str, object]:
    with patch.object(XeroInvoiceManager, "get_xero_id", return_value=str(invoice.xero_id)):
        return dict(manager.delete_document(void_approved=void_approved))


class TestDeleteRule:
    """Owner ruling 2026-10-19: a draft is deleted; an approved invoice is never
    just deleted. The user is offered a void, decided from the local copy so
    Xero only ever sees the one write that does the work."""

    def test_a_draft_is_deleted_in_one_write(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        draft = make_invoice(company, job=job, status="DRAFT", number="INV-D1")
        provider = Mock()
        provider.delete_invoice.return_value = DocumentResult(
            success=True, external_id=str(draft.xero_id), document_status="DELETED"
        )

        response = _delete(
            _manager(company, job, office_staff, provider), draft, void_approved=False
        )

        assert response["success"] is True
        assert provider.delete_invoice.call_args.kwargs["void"] is False
        assert not Invoice.objects.filter(id=draft.id).exists()
        assert JobEvent.objects.filter(job=job, event_type="invoice_deleted").exists()

    def test_an_approved_invoice_is_refused_without_calling_xero(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        approved = make_invoice(company, job=job, status="AUTHORISED", number="INV-A1")
        provider = Mock()

        response = _delete(
            _manager(company, job, office_staff, provider), approved, void_approved=False
        )

        assert response["success"] is False
        assert response["error_type"] == INVOICE_APPROVED
        assert "INV-A1 is already approved" in str(response["error"])
        provider.delete_invoice.assert_not_called()
        assert Invoice.objects.filter(id=approved.id).exists()

    def test_a_confirmed_void_keeps_the_invoice_marked_voided(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        approved = make_invoice(company, job=job, status="AUTHORISED", number="INV-A2")
        provider = Mock()
        provider.delete_invoice.return_value = DocumentResult(
            success=True, external_id=str(approved.xero_id), document_status="VOIDED"
        )

        response = _delete(
            _manager(company, job, office_staff, provider), approved, void_approved=True
        )

        assert response["success"] is True
        assert provider.delete_invoice.call_args.kwargs["void"] is True
        approved.refresh_from_db()
        assert approved.status == "VOIDED"
        assert JobEvent.objects.filter(job=job, event_type="invoice_voided").exists()

    def test_a_part_paid_invoice_is_refused_without_calling_xero(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        part_paid = make_invoice(
            company,
            job=job,
            status="AUTHORISED",
            number="INV-P1",
            total_excl_tax=Decimal("100.00"),
            amount_due=Decimal("15.00"),
        )
        provider = Mock()

        response = _delete(
            _manager(company, job, office_staff, provider), part_paid, void_approved=True
        )

        assert response["success"] is False
        assert "payment or credit note" in str(response["error"])
        provider.delete_invoice.assert_not_called()

    def test_a_xero_refusal_stops_with_nothing_changed(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """Xero refusing what the local copy allowed means the two disagree:
        stop, show Xero's reason, offer nothing (ADR 0015)."""
        stale = make_invoice(company, job=job, status="DRAFT", number="INV-S1")
        provider = Mock()
        provider.delete_invoice.return_value = DocumentResult(
            success=False, error="Invoice not of valid status for modification", status_code=400
        )

        response = _delete(
            _manager(company, job, office_staff, provider), stale, void_approved=False
        )

        assert response["success"] is False
        assert response["error"] == "Invoice not of valid status for modification"
        assert "error_type" not in response
        stale.refresh_from_db()
        assert stale.status == "DRAFT"
        assert not JobEvent.objects.filter(job=job, event_type="invoice_deleted").exists()

    def test_a_voided_invoice_is_refused_without_calling_xero(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        voided = make_invoice(company, job=job, status="VOIDED", number="INV-V1")
        provider = Mock()

        response = _delete(
            _manager(company, job, office_staff, provider), voided, void_approved=True
        )

        assert response["success"] is False
        provider.delete_invoice.assert_not_called()
        assert Invoice.objects.filter(id=voided.id).exists()

    def test_a_zero_dollar_paid_invoice_is_refused_without_claiming_a_payment(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """Xero marks a $0 invoice PAID on approval; there is no payment to remove."""
        zero = make_invoice(
            company,
            job=job,
            status="PAID",
            number="INV-Z1",
            total_excl_tax=Decimal("0.00"),
            amount_due=Decimal("0.00"),
        )
        provider = Mock()

        response = _delete(_manager(company, job, office_staff, provider), zero, void_approved=True)

        assert response["error"] == (
            "INV-Z1 is marked paid in Xero, so it can't be voided here. Open it in Xero, "
            "remove any payment on it, then void it there."
        )
        provider.delete_invoice.assert_not_called()

    def test_a_submitted_invoice_deletes_rather_than_offering_a_void(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """Docketworks records the drafts it raises as SUBMITTED."""
        submitted = make_invoice(company, job=job, status="SUBMITTED", number="INV-U1")
        provider = Mock()
        provider.delete_invoice.return_value = DocumentResult(
            success=True, external_id=str(submitted.xero_id), document_status="DELETED"
        )

        response = _delete(
            _manager(company, job, office_staff, provider), submitted, void_approved=False
        )

        assert response["success"] is True
        assert provider.delete_invoice.call_args.kwargs["void"] is False

    def test_xero_reporting_another_state_stops(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        approved = make_invoice(company, job=job, status="AUTHORISED", number="INV-M1")
        provider = Mock()
        provider.delete_invoice.return_value = DocumentResult(
            success=True, external_id=str(approved.xero_id), document_status="DELETED"
        )

        with pytest.raises(ValueError, match="INV-M1"):
            _delete(_manager(company, job, office_staff, provider), approved, void_approved=True)

        approved.refresh_from_db()
        assert approved.status == "AUTHORISED"
