"""The live provider's document methods, against a mocked Xero API.

Business risk covered: every other test mocks the provider itself, so without
these the payload construction (None-stripping, PascalCase, float coercion),
the error-result conversion, and the PO zero-UUID recovery ship unexercised —
and they only ever run against live Xero, where a defect is a real document.
"""

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from apps.accounting.types import DocumentLineItem, InvoicePayload, POPayload
from apps.xero.models import XeroAccount
from apps.xero.provider import XeroAccountingProvider
from apps.xero.readonly_provider import XeroReadOnlyProvider

pytestmark = pytest.mark.django_db

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


class _FakeApiError(Exception):
    """Duck-typed like the SDK's ApiException: .body and .status."""

    def __init__(self, body: str, status: int) -> None:
        super().__init__("API error")
        self.body = body
        self.status = status


def _invoice_payload() -> InvoicePayload:
    return InvoicePayload(
        client_external_id=str(uuid.uuid4()),
        company_name="Provider Test Co",
        line_items=[
            DocumentLineItem(
                description="Job: 1 - Test",
                quantity=Decimal("1"),
                unit_amount=Decimal("100.00"),
                account_code="200",
            )
        ],
        date=date(2026, 8, 9),
        due_date=date(2026, 9, 20),
        document_theme_external_id=str(uuid.uuid4()),
        reference=None,
        url="https://example.test/jobs/1",
    )


def _po_payload(external_id: str | None = None) -> POPayload:
    return POPayload(
        supplier_external_id=str(uuid.uuid4()),
        supplier_name="Provider Supplier",
        po_number="PO-PROV-1",
        line_items=[
            DocumentLineItem(
                description="Steel",
                quantity=Decimal("2"),
                unit_amount=Decimal("50.00"),
                account_code="300",
            )
        ],
        date=date(2026, 8, 9),
        status="DRAFT",
        external_id=external_id,
    )


def _provider_with_api() -> tuple[XeroAccountingProvider, Mock]:
    provider = XeroAccountingProvider()
    api = Mock()
    patcher = patch.object(XeroAccountingProvider, "_get_api", return_value=(api, "tenant-test"))
    patcher.start()
    return provider, api


@pytest.fixture(autouse=True)
def _stop_patches() -> "Iterator[None]":
    yield
    patch.stopall()


class TestPayloadHelpers:
    def test_to_xero_payload_strips_nones_and_pascal_cases(self) -> None:
        obj = Mock()
        obj.to_dict.return_value = {
            "invoice_id": "abc",
            "reference": None,
            "line_items": [{"unit_amount": 1.0, "item_code": None}],
        }
        result = XeroAccountingProvider._to_xero_payload(obj)
        assert result == {"InvoiceID": "abc", "LineItems": [{"UnitAmount": 1.0}]}

    def test_build_line_items_coerces_decimals_to_float(self) -> None:
        [line] = XeroAccountingProvider._build_line_items(_invoice_payload().line_items)
        assert line.quantity == 1.0
        assert isinstance(line.quantity, float)
        assert line.unit_amount == 100.0
        assert line.account_code == "200"

    def test_make_error_result_parses_xero_body(self) -> None:
        exc = _FakeApiError(
            body='{"Elements": [{"ValidationErrors": [{"Message": "Contact is archived"}]}]}',
            status=400,
        )
        result = XeroAccountingProvider._make_error_result(exc)
        assert not result.success
        assert result.error == "Contact is archived"
        assert result.status_code == 400

    def test_make_error_result_defaults_to_500(self) -> None:
        result = XeroAccountingProvider._make_error_result(RuntimeError("boom"))
        assert result.status_code == 500
        assert result.error == "boom"


class TestCreateInvoice:
    def test_success_returns_document_result(self) -> None:
        provider, api = _provider_with_api()
        invoice_id = str(uuid.uuid4())
        created = SimpleNamespace(
            invoice_id=invoice_id,
            invoice_number="INV-0042",
            _sub_total=100.0,
            _total_tax=15.0,
            _total=115.0,
        )
        api.create_invoices.return_value = SimpleNamespace(invoices=[created])

        result = provider.create_invoice(_invoice_payload())

        assert result.success
        assert result.external_id == invoice_id
        assert result.number == "INV-0042"
        assert result.online_url == f"https://go.xero.com/app/invoicing/edit/{invoice_id}"
        # The posted body is the cleaned PascalCase dict, not an SDK object.
        posted = api.create_invoices.call_args.kwargs["invoices"]["Invoices"][0]
        assert posted["Type"] == "ACCREC"
        assert "Reference" not in posted  # None was stripped

    def test_empty_response_is_an_error_result(self) -> None:
        provider, api = _provider_with_api()
        api.create_invoices.return_value = SimpleNamespace(invoices=[])

        result = provider.create_invoice(_invoice_payload())

        assert not result.success
        assert result.error is not None and "no invoices" in result.error

    def test_api_exception_becomes_error_result(self) -> None:
        provider, api = _provider_with_api()
        api.create_invoices.side_effect = _FakeApiError(
            body='{"Message": "Rate limit exceeded"}', status=429
        )

        result = provider.create_invoice(_invoice_payload())

        assert not result.success
        assert result.error == "Rate limit exceeded"
        assert result.status_code == 429


class TestDeleteInvoice:
    def test_pre_reads_then_upserts_deleted(self) -> None:
        provider, api = _provider_with_api()
        external_id = str(uuid.uuid4())
        api.get_invoice.return_value = SimpleNamespace(
            invoices=[SimpleNamespace(contact=SimpleNamespace(contact_id="c-1"), date="2026-08-01")]
        )
        api.update_or_create_invoices.return_value = SimpleNamespace(invoices=[])

        result = provider.delete_invoice(external_id)

        assert result.success
        assert result.external_id == external_id
        posted = api.update_or_create_invoices.call_args.kwargs["invoices"]["Invoices"][0]
        assert posted["Status"] == "DELETED"
        assert posted["InvoiceID"] == external_id


class TestPurchaseOrders:
    def _upsert_response(self, po_id: str, number: str = "PO-PROV-1") -> SimpleNamespace:
        result_po = Mock()
        result_po.purchase_order_id = po_id
        result_po.purchase_order_number = number
        result_po.validation_errors = None
        result_po.to_dict.return_value = {"line_items": [{"line_item_id": "li-1"}]}
        return SimpleNamespace(purchase_orders=[result_po])

    def test_create_success(self) -> None:
        provider, api = _provider_with_api()
        po_id = str(uuid.uuid4())
        api.update_or_create_purchase_orders.return_value = self._upsert_response(po_id)

        result = provider.create_purchase_order(_po_payload())

        assert result.success
        assert result.external_id == po_id
        assert result.number == "PO-PROV-1"
        assert result.raw_response is not None
        assert result.raw_response["line_items"] == [{"line_item_id": "li-1"}]

    def test_update_requires_external_id(self) -> None:
        provider, _api = _provider_with_api()
        with pytest.raises(ValueError, match="external_id"):
            provider.update_purchase_order(_po_payload())

    def test_zero_uuid_recovers_real_id_across_pages(self) -> None:
        provider, api = _provider_with_api()
        real_id = str(uuid.uuid4())
        api.update_or_create_purchase_orders.return_value = self._upsert_response(ZERO_UUID)
        other = Mock()
        other.purchase_order_number = "PO-OTHER"
        recovered = Mock()
        recovered.purchase_order_id = real_id
        recovered.purchase_order_number = "PO-PROV-1"
        recovered.validation_errors = None
        recovered.to_dict.return_value = {"line_items": []}
        api.get_purchase_orders.side_effect = [
            SimpleNamespace(purchase_orders=[other]),
            SimpleNamespace(purchase_orders=[recovered]),
        ]

        result = provider.create_purchase_order(_po_payload())

        assert result.success
        assert result.external_id == real_id
        pages = [call.kwargs["page"] for call in api.get_purchase_orders.call_args_list]
        assert pages == [1, 2]

    def test_zero_uuid_unrecovered_stays_out_of_external_id_on_validation_error(self) -> None:
        provider, api = _provider_with_api()
        result_po = Mock()
        result_po.purchase_order_id = ZERO_UUID
        result_po.purchase_order_number = "PO-PROV-1"
        result_po.validation_errors = [Mock(message="Missing account code")]
        api.update_or_create_purchase_orders.return_value = SimpleNamespace(
            purchase_orders=[result_po]
        )
        api.get_purchase_orders.return_value = SimpleNamespace(purchase_orders=[])

        result = provider.create_purchase_order(_po_payload())

        assert not result.success
        assert result.external_id is None
        assert result.validation_errors == ["Missing account code"]

    def test_zero_uuid_unrecovered_is_a_failure_not_a_sentinel_success(self) -> None:
        provider, api = _provider_with_api()
        api.update_or_create_purchase_orders.return_value = self._upsert_response(ZERO_UUID)
        api.get_purchase_orders.return_value = SimpleNamespace(purchase_orders=[])

        result = provider.create_purchase_order(_po_payload())

        assert not result.success
        assert result.external_id is None
        assert result.error is not None and "zero UUID" in result.error

    def test_delete_pre_reads_then_upserts_deleted(self) -> None:
        provider, api = _provider_with_api()
        external_id = str(uuid.uuid4())
        api.get_purchase_order.return_value = SimpleNamespace(
            purchase_orders=[
                SimpleNamespace(contact=SimpleNamespace(contact_id="c-1"), date="2026-08-01")
            ]
        )
        api.update_or_create_purchase_orders.return_value = SimpleNamespace(purchase_orders=[])

        result = provider.delete_purchase_order(external_id)

        assert result.success
        posted = api.update_or_create_purchase_orders.call_args.kwargs["purchase_orders"][
            "PurchaseOrders"
        ][0]
        assert posted["Status"] == "DELETED"


class TestAttachmentsAndNotes:
    def test_attach_file_success(self) -> None:
        provider, api = _provider_with_api()
        assert provider.attach_file_to_invoice("inv-1", "workshop.pdf", b"pdf") is True
        api.create_invoice_attachment_by_file_name.assert_called_once()

    def test_attach_file_failure_returns_false_and_persists(self) -> None:
        provider, api = _provider_with_api()
        api.create_invoice_attachment_by_file_name.side_effect = RuntimeError("boom")
        assert provider.attach_file_to_invoice("inv-1", "workshop.pdf", b"pdf") is False

    def test_history_notes_route_by_kind(self) -> None:
        provider, api = _provider_with_api()
        assert provider.add_history_note_to_invoice("inv-1", "note") is True
        api.create_invoice_history.assert_called_once()
        assert provider.add_history_note_to_quote("q-1", "note") is True
        api.create_quote_history.assert_called_once()

    def test_history_note_failure_returns_false(self) -> None:
        provider, api = _provider_with_api()
        api.create_invoice_history.side_effect = RuntimeError("boom")
        assert provider.add_history_note_to_invoice("inv-1", "note") is False


class TestGetAccountCode:
    def test_returns_code(self) -> None:
        XeroAccount.objects.create(
            xero_id=uuid.uuid4(),
            account_code="200",
            account_name="Sales",
            xero_last_modified=timezone.now(),
            raw_json={},
        )
        assert XeroAccountingProvider().get_account_code("Sales") == "200"

    def test_missing_code_raises(self) -> None:
        XeroAccount.objects.create(
            xero_id=uuid.uuid4(),
            account_code=None,
            account_name="Sales",
            xero_last_modified=timezone.now(),
            raw_json={},
        )
        with pytest.raises(ValueError, match="no account code"):
            XeroAccountingProvider().get_account_code("Sales")


class TestReadonlyDocumentStubs:
    def test_po_create_and_update_fabricate(self) -> None:
        provider = XeroReadOnlyProvider()

        created = provider.create_purchase_order(_po_payload())
        assert created.success
        assert created.number == "PO-PROV-1"
        assert created.raw_response == {"line_items": [], "_e2e_stub": True}

        existing = str(uuid.uuid4())
        updated = provider.update_purchase_order(_po_payload(external_id=existing))
        assert updated.external_id == existing

        with pytest.raises(ValueError, match="external_id"):
            provider.update_purchase_order(_po_payload())

    def test_delete_stubs_succeed_without_pre_read(self) -> None:
        provider = XeroReadOnlyProvider()
        assert provider.delete_invoice(str(uuid.uuid4())).success
        assert provider.delete_purchase_order(str(uuid.uuid4())).success

    def test_attach_and_notes_report_success(self) -> None:
        provider = XeroReadOnlyProvider()
        assert provider.attach_file_to_invoice("inv-1", "workshop.pdf", b"pdf") is True
        assert provider.add_history_note_to_invoice("inv-1", "note") is True
        assert provider.add_history_note_to_quote("q-1", "note") is True

    def test_shared_helpers_are_tripwired(self) -> None:
        provider = XeroReadOnlyProvider()
        with pytest.raises(RuntimeError, match="override is missing"):
            provider._add_history_note("invoice", "inv-1", "note")
        with pytest.raises(RuntimeError, match="override is missing"):
            provider._create_or_update_purchase_order(_po_payload())
