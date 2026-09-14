"""Every object the fake creates is queryable exactly as Xero's would be (ADR 0060).

Business risk covered: the application creates in one call and finds in
another — the duplicate check by name, the sync by modified-since and
type, the cleanup by id — and a fake that answered the create but not the
find would pass a run on an object Xero would then have lost. For every
write route, what it creates is read back by id, listed, found through
every filter the resource offers on the values it holds, and reached
through its owner.
"""

import uuid
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from django.db import models
from xero_python.accounting import AccountingApi
from xero_python.exceptions import ApiException

from apps.xero.fake.models import (
    Document,
    FakeContact,
    FakeHistoryRecord,
    FakeInvoice,
    FakeItem,
    FakePurchaseOrder,
    FakeQuote,
    XeroRecord,
)
from apps.xero.fake.tests.conftest import TENANT, THEME

pytestmark = pytest.mark.django_db


def _contact(accounting: AccountingApi) -> str:
    created = accounting.create_contacts(
        TENANT,
        contacts={
            "contacts": [
                {
                    "Name": f"[TEST] Queryable {uuid.uuid4().hex[:6]}",
                    "EmailAddress": "hello@example.test",
                    "FirstName": "Ada",
                    "LastName": "Lovelace",
                    "AccountNumber": "ACC-7",
                    "IsCustomer": True,
                }
            ]
        },
    ).contacts
    assert created is not None and created[0].contact_id is not None
    return created[0].contact_id


def _document(kind: str, contact_id: str) -> dict[str, object]:
    return {
        "Contact": {"ContactID": contact_id},
        "LineItems": [
            {"Description": "widgets", "Quantity": 2, "UnitAmount": "10.50", "AccountCode": "200"}
        ],
        "Date": "2026-09-09",
        "Reference": "PO 42",
        "BrandingThemeID": THEME,
        **(
            {"Type": "ACCREC", "DueDate": "2026-09-16", "Status": "AUTHORISED"}
            if kind == "Invoices"
            else {"ExpiryDate": "2026-10-09", "Status": "DRAFT"}
            if kind == "Quotes"
            else {"DeliveryDate": "2026-09-12", "Status": "SUBMITTED"}
        ),
    }


def _create_invoice(accounting: AccountingApi) -> str:
    created = accounting.create_invoices(
        TENANT, invoices={"Invoices": [_document("Invoices", _contact(accounting))]}
    ).invoices
    assert created is not None and created[0].invoice_id is not None
    return created[0].invoice_id


def _create_quote(accounting: AccountingApi) -> str:
    created = accounting.create_quotes(
        TENANT, quotes={"Quotes": [_document("Quotes", _contact(accounting))]}
    ).quotes
    assert created is not None and created[0].quote_id is not None
    return created[0].quote_id


def _create_purchase_order(accounting: AccountingApi) -> str:
    created = accounting.update_or_create_purchase_orders(
        TENANT,
        purchase_orders={"PurchaseOrders": [_document("PurchaseOrders", _contact(accounting))]},
    ).purchase_orders
    assert created is not None and created[0].purchase_order_id is not None
    return str(created[0].purchase_order_id)


def _create_item(accounting: AccountingApi) -> str:
    created = accounting.update_or_create_items(
        TENANT,
        items={
            "Items": [
                {
                    "Code": f"SKU-{uuid.uuid4().hex[:6]}",
                    "Name": "Steel sheet",
                    "IsSold": True,
                    "IsPurchased": True,
                    "SalesDetails": {"UnitPrice": 12.5, "AccountCode": "200"},
                }
            ]
        },
    ).items
    assert created is not None and created[0].item_id is not None
    return str(created[0].item_id)


#: Every write route creating a resource whose listing takes ``where``, with that listing
#: and whether it also takes Xero's ``IDs`` parameter (contacts and invoices do). Quotes
#: and purchase orders are listed through their own parameters, tested below.
_WRITES: list[tuple[type[XeroRecord], Callable[[AccountingApi], str], str, bool]] = [
    (FakeContact, _contact, "get_contacts", True),
    (FakeInvoice, _create_invoice, "get_invoices", True),
    (FakeItem, _create_item, "get_items", False),
]


def _literal(value: object) -> str:
    """Spell a column's value in Xero's filter grammar."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, UUID):
        return f'Guid("{value}")'
    if isinstance(value, datetime):
        return f"DateTime({value.year},{value.month},{value.day})"
    if isinstance(value, date):
        return f"DateTime({value.year},{value.month},{value.day})"
    if isinstance(value, Decimal):
        return str(value.normalize())
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _ids_of(listing: object, resource: str) -> set[str]:
    elements = getattr(listing, resource)
    assert elements is not None
    id_attr = {"contacts": "contact_id", "invoices": "invoice_id", "items": "item_id"}[resource]
    return {str(getattr(element, id_attr)) for element in elements}


@pytest.mark.parametrize(
    ("model", "create", "listing", "takes_ids"), _WRITES, ids=[m.__name__ for m, *_ in _WRITES]
)
def test_what_a_write_creates_is_found_by_id_in_the_listing_and_through_every_filter(
    accounting: AccountingApi,
    model: type[XeroRecord],
    create: Callable[[AccountingApi], str],
    listing: str,
    takes_ids: bool,
) -> None:
    created_id = create(accounting)
    row = model.held(TENANT, created_id)
    assert row is not None, "created but not held under its id"
    resource = listing.removeprefix("get_")
    list_route = getattr(accounting, listing)

    assert created_id in _ids_of(list_route(TENANT), resource)
    if takes_ids:
        assert created_id in _ids_of(list_route(TENANT, i_ds=[created_id]), resource)

    for key, column in model.WIRE.items():
        value = getattr(row, column)
        field = model._meta.get_field(column)
        if value is None or isinstance(field, models.TextField):
            continue
        if isinstance(field, models.DateTimeField):
            # A timestamp is filtered by range, as the sync does.
            clause = f"{key}>={_literal(value)}"
        else:
            clause = f"{key}=={_literal(value)}"
        found = _ids_of(list_route(TENANT, where=clause), resource)
        assert created_id in found, f"{model.__name__} not found by {clause}"

    if isinstance(row, Document):
        assert row.contact is not None
        through_owner = _ids_of(
            list_route(TENANT, where=f'Contact.ContactID==Guid("{row.contact.id}")'), resource
        )
        assert created_id in through_owner
        assert created_id in _ids_of(
            list_route(TENANT, if_modified_since=row.updated_date_utc), resource
        )


def test_a_created_quote_is_found_through_the_quote_listing_s_own_filters(
    accounting: AccountingApi,
) -> None:
    quote_id = _create_quote(accounting)
    row = FakeQuote.held(TENANT, quote_id)
    assert row is not None and row.contact is not None
    found = accounting.get_quotes(
        TENANT,
        status="DRAFT",
        contact_id=str(row.contact.id),
        quote_number=row.number,
        date_from=row.date,
        date_to=row.date,
        expiry_date_from=row.expiry_date,
        expiry_date_to=row.expiry_date,
    ).quotes
    assert found is not None and [str(quote.quote_id) for quote in found] == [quote_id]
    one = accounting.get_quote(TENANT, quote_id).quotes
    assert one is not None and one[0].quote_number == row.number
    missed = accounting.get_quotes(TENANT, status="ACCEPTED").quotes
    assert not missed


def test_a_created_purchase_order_is_found_through_its_listing_s_own_filters(
    accounting: AccountingApi,
) -> None:
    order_id = _create_purchase_order(accounting)
    row = FakePurchaseOrder.held(TENANT, order_id)
    assert row is not None and row.date is not None
    found = accounting.get_purchase_orders(
        TENANT, status="SUBMITTED", date_from=row.date.isoformat(), date_to=row.date.isoformat()
    ).purchase_orders
    assert found is not None and [str(order.purchase_order_id) for order in found] == [order_id]
    one = accounting.get_purchase_order(TENANT, order_id).purchase_orders
    assert one is not None and one[0].purchase_order_number
    missed = accounting.get_purchase_orders(TENANT, status="BILLED").purchase_orders
    assert not missed


def test_a_history_note_is_read_back_from_its_document(accounting: AccountingApi) -> None:
    invoice_id = _create_invoice(accounting)
    accounting.create_invoice_history(
        TENANT, invoice_id, {"HistoryRecords": [{"Details": "Job #7 raised"}]}
    )
    notes = accounting.get_invoice_history(TENANT, invoice_id).history_records
    assert notes is not None and [note.details for note in notes] == ["Job #7 raised"]
    assert (
        FakeHistoryRecord.objects.filter(document_id=invoice_id, resource="Invoices").count() == 1
    )
    with pytest.raises(ApiException) as refused:
        accounting.get_invoice_history(TENANT, str(uuid.uuid4()))
    assert refused.value.status == 404
