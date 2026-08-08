"""The webhook per-resource sync paths, exercised directly.

Business risk covered: every other test mocks these functions and E2E cannot
reach them (Xero must deliver the webhook), so without direct tests the
ACCPAY/ACCREC routing and the webhook-path unarchive fix ship unexercised.
"""

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from apps.accounting.models import Bill, Invoice
from apps.company.models import Company
from apps.xero.single_sync import sync_single_contact, sync_single_invoice

from .xero_fixtures import make_xero_contact

pytestmark = pytest.mark.django_db

TENANT = "tenant-test"


@pytest.fixture(autouse=True)
def _stub_api_client() -> object:
    """Building a real ApiClient needs an active XeroApp row; none is needed
    here — the AccountingApi itself is mocked in every test.
    """
    with patch("apps.xero.single_sync.get_api_client", return_value=Mock()):
        yield


def _contacts_response(contact: Any) -> SimpleNamespace:
    return SimpleNamespace(contacts=[contact])


class TestSyncSingleContact:
    def test_creates_company_from_webhook_contact(self) -> None:
        contact = make_xero_contact("wh-contact-1", "Webhook Created Ltd")
        api = Mock()
        api.get_contacts.return_value = _contacts_response(contact)

        with patch("apps.xero.single_sync.AccountingApi", return_value=api):
            sync_single_contact(TENANT, "wh-contact-1")

        company = Company.objects.get(xero_contact_id="wh-contact-1")
        assert company.name == "Webhook Created Ltd"
        api.get_contacts.assert_called_once()

    def test_webhook_unarchive_restores_allow_jobs(self) -> None:
        """The webhook path fires the ADR 0034 restore (dead in v1 on BOTH paths).

        The pre-write of xero_archived that killed the was_archived
        transition was removed here exactly as on the batch path (ledgered).
        """
        company = Company.objects.create(
            name="Webhook Unarchive Ltd",
            xero_last_modified=timezone.now(),
            xero_contact_id="wh-contact-2",
            xero_archived=True,
            allow_jobs=False,
        )
        contact = make_xero_contact("wh-contact-2", "Webhook Unarchive Ltd")
        api = Mock()
        api.get_contacts.return_value = _contacts_response(contact)

        with patch("apps.xero.single_sync.AccountingApi", return_value=api):
            sync_single_contact(TENANT, "wh-contact-2")

        company.refresh_from_db()
        assert not company.xero_archived
        assert company.allow_jobs

    def test_missing_contact_raises(self) -> None:
        api = Mock()
        api.get_contacts.return_value = SimpleNamespace(contacts=[])

        with (
            patch("apps.xero.single_sync.AccountingApi", return_value=api),
            pytest.raises(ValueError, match="No contact found"),
        ):
            sync_single_contact(TENANT, "missing-id")


class _FakeXeroInvoice:
    """SDK-shaped: public attrs the router reads, underscored slots that
    serialize into the raw_json set_invoice_or_bill_fields derives from."""

    def __init__(self, doc_type: str, xero_id: str, company: Company) -> None:
        self.type = doc_type
        self.invoice_id = xero_id
        self._updated_date_utc = timezone.now()
        self._type = doc_type
        self._invoice_id = xero_id
        self._invoice_number = f"DOC-{xero_id[:8]}"
        self._date = "2026-08-01"
        self._due_date = "2026-08-20"
        self._status = "AUTHORISED"
        self._total_tax = 15.0
        self._sub_total = 100.0
        self._total = 115.0
        self._amount_due = 115.0
        self._contact = {"_contact_id": company.xero_contact_id}
        self._line_items: list[object] = []
        self._line_amount_types = {"_value_": "Exclusive"}


class TestSyncSingleInvoiceRouting:
    @pytest.fixture
    def company(self) -> Company:
        return Company.objects.create(
            name="Webhook Doc Co",
            xero_last_modified=timezone.now(),
            xero_contact_id="wh-doc-contact",
        )

    def _run(self, doc_type: str, xero_id: str, company: Company) -> None:
        api = Mock()
        api.get_invoice.return_value = SimpleNamespace(
            invoices=[_FakeXeroInvoice(doc_type, xero_id, company)]
        )
        with patch("apps.xero.single_sync.AccountingApi", return_value=api):
            sync_single_invoice(TENANT, xero_id)

    def _seed(self, model: type[Invoice] | type[Bill], xero_id: str, company: Company) -> None:
        """Webhook updates require an existing row: creating a NEW document
        via webhook dies on NOT-NULL defaults (v1-inherited; the hourly sync
        owns creation). Seed the row the webhook will refresh."""
        model.objects.create(
            xero_id=xero_id,
            number=f"SEED-{xero_id[:8]}",
            company=company,
            date="2026-07-01",
            status="DRAFT",
            total_excl_tax=1,
            tax=0,
            total_incl_tax=1,
            amount_due=1,
            xero_last_modified=timezone.now(),
            raw_json={},
        )

    def test_accrec_routes_to_invoice(self, company: Company) -> None:
        xero_id = str(uuid.uuid4())
        self._seed(Invoice, xero_id, company)
        self._run("ACCREC", xero_id, company)

        invoice = Invoice.objects.get(xero_id=xero_id)
        assert invoice.company == company
        # The webhook refreshed the row from the new payload.
        assert invoice.status == "AUTHORISED"
        assert not Bill.objects.filter(xero_id=xero_id).exists()

    def test_accpay_routes_to_bill(self, company: Company) -> None:
        xero_id = str(uuid.uuid4())
        self._seed(Bill, xero_id, company)
        self._run("ACCPAY", xero_id, company)

        bill = Bill.objects.get(xero_id=xero_id)
        assert bill.company == company
        assert bill.status == "AUTHORISED"
        assert not Invoice.objects.filter(xero_id=xero_id).exists()

    def test_unknown_type_raises(self, company: Company) -> None:
        with pytest.raises(ValueError, match="Unknown invoice type"):
            self._run("ACCRECCREDIT", str(uuid.uuid4()), company)
