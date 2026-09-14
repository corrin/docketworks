"""The fake answers the Accounting API calls the application makes, through the real SDK (ADR 0060).

Business risk covered: an iteration run trusts these answers for every
contact, invoice, quote and purchase order it pushes. An id that repeated, a
total that disagreed with the lines, a page that skipped a row or a refusal
that read as success would make the run green on a behaviour the real gate
would fail — or, worse, pass a bug through to the real gate that the fake
had been hiding.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from xero_python.accounting import AccountingApi, Contact, Phone, QuoteLineAmountTypes
from xero_python.api_client import ApiClient
from xero_python.exceptions import ApiException

from apps.xero.constants import ZERO_UUID
from apps.xero.fake.http import FakeXeroUnhandledRouteError
from apps.xero.fake.models import FakeAttachment
from apps.xero.fake.tests.conftest import TENANT, THEME
from apps.xero.fake.wire import Json

pytestmark = pytest.mark.django_db


def _contact(accounting: AccountingApi, name: str) -> str:
    """Create a contact the way contacts.create_company_contact_in_xero does; return its id."""
    response = accounting.create_contacts(
        TENANT,
        contacts={
            "contacts": [
                Contact(
                    name=name,
                    email_address="hello@example.test",
                    phones=[Phone(phone_type="DEFAULT", phone_number="09 111 1111")],
                    is_customer=True,
                )
            ]
        },
    )
    assert response.contacts is not None
    contact_id = response.contacts[0].contact_id
    assert contact_id is not None
    return contact_id


def _invoice_payload(contact_id: str, *, status: str = "AUTHORISED") -> dict[str, Json]:
    """What provider.create_invoice sends, after _to_xero_payload."""
    return {
        "Type": "ACCREC",
        "Contact": {"ContactID": contact_id, "Name": "[TEST] Client"},
        "LineItems": [
            {
                "Description": "Job: 1 - widgets",
                "Quantity": 2,
                "UnitAmount": "10.50",
                "AccountCode": "200",
                "TaxType": "OUTPUT2",
            }
        ],
        "Date": "2026-09-09",
        "DueDate": "2026-09-16",
        "LineAmountTypes": "Exclusive",
        "CurrencyCode": "NZD",
        "Status": status,
        "Reference": "PO 42",
        "BrandingThemeID": THEME,
    }


class TestContacts:
    def test_a_created_contact_carries_xero_defaults_and_a_unique_id(
        self, accounting: AccountingApi
    ) -> None:
        first = _contact(accounting, "[TEST] First")
        second = _contact(accounting, "[TEST] Second")
        assert first != second
        uuid.UUID(first)

        found = accounting.get_contact(TENANT, first).contacts
        assert found is not None
        contact = found[0]
        assert contact.contact_status == "ACTIVE"
        assert contact.name == "[TEST] First"
        assert contact.phones is not None
        assert [phone.phone_type for phone in contact.phones] == ["DDI", "DEFAULT", "FAX", "MOBILE"]
        assert contact.phones[1].phone_number == "09 111 1111"
        assert contact.updated_date_utc is not None
        assert datetime.now(tz=UTC) - contact.updated_date_utc < timedelta(minutes=1)

    def test_the_duplicate_check_finds_a_contact_by_exact_name(
        self, accounting: AccountingApi
    ) -> None:
        created = _contact(accounting, '[TEST] Quote "Co"')
        hits = accounting.get_contacts(TENANT, where='Name=="[TEST] Quote \\"Co\\""').contacts
        misses = accounting.get_contacts(TENANT, where='Name=="[TEST] Other"').contacts
        assert hits is not None and [hit.contact_id for hit in hits] == [created]
        assert not misses

    def test_an_unknown_id_is_xero_s_404(self, accounting: AccountingApi) -> None:
        with pytest.raises(ApiException) as refused:
            accounting.get_contact(TENANT, str(uuid.uuid4()))
        assert refused.value.status == 404

    def test_paging_and_the_archived_filter(self, accounting: AccountingApi) -> None:
        ids = [_contact(accounting, f"[TEST] Page {index}") for index in range(3)]
        accounting.update_or_create_contacts(
            TENANT, contacts={"contacts": [Contact(contact_id=ids[0], contact_status="ARCHIVED")]}
        )
        page_one = accounting.get_contacts(TENANT, page=1, page_size=2, include_archived=True)
        page_two = accounting.get_contacts(TENANT, page=2, page_size=2, include_archived=True)
        assert page_one.contacts is not None and len(page_one.contacts) == 2
        assert page_two.contacts is not None and len(page_two.contacts) == 1
        live = accounting.get_contacts(TENANT, include_archived=False).contacts
        assert live is not None and {contact.contact_id for contact in live} == set(ids[1:])

    def test_modified_since_returns_only_what_changed_after_it(
        self, accounting: AccountingApi
    ) -> None:
        _contact(accounting, "[TEST] Old")
        cursor = datetime.now(tz=UTC).isoformat()
        newer = _contact(accounting, "[TEST] New")
        since = accounting.get_contacts(TENANT, if_modified_since=cursor).contacts
        assert since is not None and [contact.contact_id for contact in since] == [newer]

    def test_archiving_succeeds_with_an_invoice_standing_and_is_refused_once_archived(
        self, accounting: AccountingApi
    ) -> None:
        # recordings/contact_archive_with_documents.json and contact_archive_archived.json
        contact_id = _contact(accounting, "[TEST] Busy")
        accounting.create_invoices(TENANT, invoices={"Invoices": [_invoice_payload(contact_id)]})

        def archive() -> list[Contact]:
            response = accounting.update_or_create_contacts(
                TENANT,
                contacts={"contacts": [Contact(contact_id=contact_id, contact_status="ARCHIVED")]},
                summarize_errors=False,
            )
            assert response.contacts is not None
            return response.contacts

        archived = archive()[0]
        assert archived.contact_status == "ARCHIVED" and not archived.has_validation_errors
        refused = archive()[0]
        assert refused.has_validation_errors is True
        assert refused.validation_errors and "archived contact" in str(
            refused.validation_errors[0].message
        )

    def test_a_second_active_contact_of_a_name_is_refused_in_xero_s_words(
        self, accounting: AccountingApi
    ) -> None:
        # recordings/contact_create_duplicate_name.json
        _contact(accounting, "[TEST] Twice")
        with pytest.raises(ApiException) as refused:
            _contact(accounting, "[TEST] twice")
        assert refused.value.status == 400
        assert "must be unique across all active contacts" in str(refused.value.body)


class TestInvoices:
    def test_a_created_invoice_is_numbered_totalled_and_dated_as_xero_would(
        self, accounting: AccountingApi
    ) -> None:
        contact_id = _contact(accounting, "[TEST] Client")
        first = accounting.create_invoices(
            TENANT, invoices={"Invoices": [_invoice_payload(contact_id)]}
        ).invoices
        second = accounting.create_invoices(
            TENANT, invoices={"Invoices": [_invoice_payload(contact_id)]}
        ).invoices
        assert first is not None and second is not None
        invoice = first[0]
        assert invoice.invoice_number == "INV-0001"
        assert second[0].invoice_number == "INV-0002"
        assert invoice.invoice_id != second[0].invoice_id
        # 2 x 10.50 at OUTPUT2 (15% GST, recordings/tax_rates.json)
        assert Decimal(str(invoice.sub_total)) == Decimal("21.00")
        assert Decimal(str(invoice.total_tax)) == Decimal("3.15")
        assert Decimal(str(invoice.total)) == Decimal("24.15")
        assert Decimal(str(invoice.amount_due)) == Decimal("24.15")
        # Microsoft dates on the wire, read back through the SDK's own parser
        assert invoice.date == date(2026, 9, 9)
        assert invoice.due_date == date(2026, 9, 16)
        assert invoice.contact is not None and invoice.contact.name == "[TEST] Client"
        assert invoice.line_items is not None and invoice.line_items[0].line_item_id
        assert invoice.status == "AUTHORISED"
        assert invoice.currency_code is not None

    def test_a_created_quote_echoes_the_quote_enum_whatever_casing_was_sent(
        self, accounting: AccountingApi
    ) -> None:
        # provider.create_quote sends the invoice form, "Exclusive"; Xero echoes
        # the quote enum, "EXCLUSIVE", and the SDK refuses anything else.
        contact_id = _contact(accounting, "[TEST] Client")
        created = accounting.create_quotes(
            TENANT,
            quotes={
                "Quotes": [
                    {
                        "Contact": {"ContactID": contact_id},
                        "Date": "2026-09-09",
                        "LineAmountTypes": "Exclusive",
                        "LineItems": [
                            {
                                "Description": "Job: 1 - widgets",
                                "Quantity": 1,
                                "UnitAmount": "10.50",
                                "AccountCode": "200",
                            }
                        ],
                        "Status": "DRAFT",
                    }
                ]
            },
        ).quotes
        assert created is not None
        assert created[0].line_amount_types == QuoteLineAmountTypes.EXCLUSIVE

    def test_deleting_an_authorised_invoice_is_refused_per_element(
        self, accounting: AccountingApi
    ) -> None:
        contact_id = _contact(accounting, "[TEST] Client")
        created = accounting.create_invoices(
            TENANT, invoices={"Invoices": [_invoice_payload(contact_id)]}
        ).invoices
        assert created is not None
        response = accounting.update_or_create_invoices(
            TENANT,
            invoices={
                "Invoices": [
                    {
                        "InvoiceID": created[0].invoice_id,
                        "Status": "DELETED",
                        "Contact": {"ContactID": contact_id},
                        "Date": "2026-09-09",
                    }
                ]
            },
            summarize_errors=False,
        )
        assert response.invoices is not None
        assert response.invoices[0].validation_errors

    def test_deleting_a_draft_invoice_is_a_status_change(self, accounting: AccountingApi) -> None:
        contact_id = _contact(accounting, "[TEST] Client")
        created = accounting.create_invoices(
            TENANT, invoices={"Invoices": [_invoice_payload(contact_id, status="DRAFT")]}
        ).invoices
        assert created is not None
        accounting.update_or_create_invoices(
            TENANT,
            invoices={
                "Invoices": [
                    {
                        "InvoiceID": created[0].invoice_id,
                        "Status": "DELETED",
                        "Contact": {"ContactID": contact_id},
                        "Date": "2026-09-09",
                    }
                ]
            },
        )
        again = accounting.get_invoice(TENANT, created[0].invoice_id).invoices
        assert again[0].status == "DELETED"

    def test_history_and_attachments_answer_as_written(self, accounting: AccountingApi) -> None:
        contact_id = _contact(accounting, "[TEST] Client")
        created = accounting.create_invoices(
            TENANT, invoices={"Invoices": [_invoice_payload(contact_id)]}
        ).invoices
        assert created is not None
        invoice_id = created[0].invoice_id
        assert invoice_id is not None
        notes = accounting.create_invoice_history(
            TENANT, invoice_id, {"HistoryRecords": [{"Details": "Job #7"}]}
        )
        assert notes.history_records[0].details == "Job #7"
        attached = accounting.create_invoice_attachment_by_file_name(
            TENANT, invoice_id, "workshop_7.pdf", b"%PDF-1.4 fake", include_online=False
        )
        assert attached.attachments[0].file_name == "workshop_7.pdf"
        assert FakeAttachment.objects.filter(tenant_id=TENANT, document_id=invoice_id).count() == 1


class TestPurchaseOrders:
    def _payload(self, contact_id: str, number: str, status: str) -> dict[str, Json]:
        return {
            "PurchaseOrderNumber": number,
            "Contact": {"ContactID": contact_id, "Name": "[TEST] Supplier"},
            "LineItems": [
                {"Description": "steel", "Quantity": 1, "UnitAmount": 100, "TaxType": "INPUT2"}
            ],
            "Date": "2026-09-09",
            "Status": status,
        }

    def test_create_then_update_keeps_the_id_and_moves_the_status(
        self, accounting: AccountingApi
    ) -> None:
        supplier = _contact(accounting, "[TEST] Supplier")
        created = accounting.update_or_create_purchase_orders(
            TENANT,
            purchase_orders={"PurchaseOrders": [self._payload(supplier, "PO-0009", "SUBMITTED")]},
            summarize_errors=False,
        ).purchase_orders
        assert created is not None
        po_id = created[0].purchase_order_id
        assert po_id and po_id != ZERO_UUID
        assert created[0].status == "SUBMITTED"
        updated = accounting.update_or_create_purchase_orders(
            TENANT,
            purchase_orders={
                "PurchaseOrders": [
                    {"PurchaseOrderID": po_id, **self._payload(supplier, "PO-0009", "AUTHORISED")}
                ]
            },
            summarize_errors=False,
        ).purchase_orders
        assert updated is not None
        assert updated[0].purchase_order_id == po_id
        assert updated[0].status == "AUTHORISED"
        assert Decimal(str(updated[0].total)) == Decimal("115.00")

    def test_a_number_a_deleted_order_still_holds_comes_back_as_the_zero_id(
        self, accounting: AccountingApi
    ) -> None:
        supplier = _contact(accounting, "[TEST] Supplier")
        created = accounting.update_or_create_purchase_orders(
            TENANT,
            purchase_orders={"PurchaseOrders": [self._payload(supplier, "PO-0010", "DRAFT")]},
            summarize_errors=False,
        ).purchase_orders
        assert created is not None
        accounting.update_or_create_purchase_orders(
            TENANT,
            purchase_orders={
                "PurchaseOrders": [
                    {
                        "PurchaseOrderID": created[0].purchase_order_id,
                        "Status": "DELETED",
                        "Contact": {"ContactID": supplier},
                        "Date": "2026-09-09",
                    }
                ]
            },
            summarize_errors=False,
        )
        reused = accounting.update_or_create_purchase_orders(
            TENANT,
            purchase_orders={"PurchaseOrders": [self._payload(supplier, "PO-0010", "DRAFT")]},
            summarize_errors=False,
        ).purchase_orders
        assert reused is not None
        assert reused[0].purchase_order_id == ZERO_UUID
        assert reused[0].validation_errors

    def test_a_billed_order_deletes_as_xero_deletes_it(self, accounting: AccountingApi) -> None:
        # recordings/purchase_order_delete_billed.json
        supplier = _contact(accounting, "[TEST] Supplier")
        created = accounting.update_or_create_purchase_orders(
            TENANT,
            purchase_orders={"PurchaseOrders": [self._payload(supplier, "PO-0011", "BILLED")]},
            summarize_errors=False,
        ).purchase_orders
        assert created is not None
        deleted = accounting.update_or_create_purchase_orders(
            TENANT,
            purchase_orders={
                "PurchaseOrders": [
                    {
                        "PurchaseOrderID": created[0].purchase_order_id,
                        "Status": "DELETED",
                        "Contact": {"ContactID": supplier},
                        "Date": "2026-09-09",
                        "PurchaseOrderNumber": "PO-0011-VOID-abcd1234",
                    }
                ]
            },
            summarize_errors=False,
        ).purchase_orders
        assert deleted is not None
        assert deleted[0].status == "DELETED" and not deleted[0].validation_errors
        assert deleted[0].purchase_order_number == "PO-0011-VOID-abcd1234"


class TestOrganisationAndRefusals:
    def test_every_answer_carries_the_quota_headers(self, accounting: AccountingApi) -> None:
        _body, status, headers = accounting.get_organisations(TENANT, _return_http_data_only=False)
        assert status == 200
        assert headers["X-DayLimit-Remaining"] == "4999"
        assert headers["X-MinLimit-Remaining"] == "59"

    def test_a_route_the_fake_does_not_serve_is_refused_not_guessed(
        self, client: ApiClient
    ) -> None:
        with pytest.raises(FakeXeroUnhandledRouteError, match="BankTransactions"):
            client.rest_client.request(
                "GET",
                "https://api.xero.com/api.xro/2.0/BankTransactions",
                headers={"xero-tenant-id": TENANT},
            )
