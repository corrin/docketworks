"""Every document the sync stores names the organisation it was fetched from.

The sync wrote invoices, bills, credit notes, quotes and purchase orders with
a Xero id and no tenant: the engine handed each entity's persist function the
tenant and five of them dropped it. These go through ``ENTITY_CONFIGS``, the
same entries a real sync runs, with documents as Xero sent them (the fake's
recordings), so losing the tenant at the entry or in the transform both fail.
"""

from typing import Any

import pytest
from django.db import models
from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.company.models import Company
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.factories import make_po_line, make_purchase_order
from apps.xero.fake.seed import recorded_body
from apps.xero.fake.tests.conftest import sdk_client_answering
from apps.xero.sync import ENTITY_CONFIGS

pytestmark = pytest.mark.django_db

RUN_TENANT = "the-run's-tenant"


def _recorded(recording: str, fetch: str, collection: str, **params: object) -> list[Any]:
    """The SDK objects a real fetch returned, read back from a recording."""
    api = AccountingApi(sdk_client_answering(recorded_body(recording)))
    documents: list[Any] = getattr(getattr(api, fetch)("any", **params), collection)
    assert documents
    return documents


def _hold_contacts(documents: list[Any]) -> None:
    """Have each document's contact on file, as a sync that ran contacts first does."""
    for document in documents:
        Company.objects.get_or_create(
            xero_contact_id=str(document.contact.contact_id),
            defaults={
                "name": f"Contact {document.contact.contact_id}",
                "xero_tenant_id": RUN_TENANT,
                "xero_last_modified": timezone.now(),
            },
        )


def _sync(entity: str, documents: list[Any]) -> None:
    persist = ENTITY_CONFIGS[entity][4]
    persist(documents, RUN_TENANT)


@pytest.mark.parametrize(
    ("entity", "recording", "fetch", "collection", "id_attr", "model"),
    [
        ("invoices", "invoices_page", "get_invoices", "invoices", "invoice_id", Invoice),
        ("bills", "bills_page", "get_invoices", "invoices", "invoice_id", Bill),
        (
            "credit_notes",
            "credit_notes_page",
            "get_credit_notes",
            "credit_notes",
            "credit_note_id",
            CreditNote,
        ),
        ("quotes", "quotes_page", "get_quotes", "quotes", "quote_id", Quote),
        (
            "purchase_orders",
            "purchase_orders_page",
            "get_purchase_orders",
            "purchase_orders",
            "purchase_order_id",
            PurchaseOrder,
        ),
    ],
)
def test_a_document_the_sync_creates_names_its_organisation(  # noqa: PLR0913, PLR0917 -- one row per table
    entity: str,
    recording: str,
    fetch: str,
    collection: str,
    id_attr: str,
    model: type[models.Model],
) -> None:
    documents = _recorded(recording, fetch, collection)
    _hold_contacts(documents)

    _sync(entity, documents)

    stored = model._default_manager.filter(xero_id__in=[getattr(d, id_attr) for d in documents])
    assert stored.exists()
    assert set(stored.values_list("xero_tenant_id", flat=True)) == {RUN_TENANT}


def test_an_invoice_stored_without_a_tenant_gains_one_when_the_sync_next_sees_it() -> None:
    # Rows the sync wrote before it recorded the tenant are not backfilled;
    # this is the only way one of them is completed.
    documents = _recorded("invoices_page", "get_invoices", "invoices")
    _hold_contacts(documents)
    _sync("invoices", documents)
    Invoice.objects.update(xero_tenant_id=None)

    _sync("invoices", documents)

    assert set(Invoice.objects.values_list("xero_tenant_id", flat=True)) == {RUN_TENANT}


def test_an_order_linked_by_its_number_records_where_the_id_came_from() -> None:
    # The link is by number alone, with no check that it is the same order
    # (owner-accepted). The tenant recorded beside the id says which
    # organisation the id belongs to and nothing about that match.
    incoming = _recorded("purchase_orders_page", "get_purchase_orders", "purchase_orders")[:1]
    _hold_contacts(incoming)
    ours = make_purchase_order(status="submitted")
    make_po_line(ours)
    PurchaseOrder.objects.filter(id=ours.id).update(po_number=incoming[0].purchase_order_number)

    _sync("purchase_orders", incoming)

    ours.refresh_from_db()
    assert str(ours.xero_id) == str(incoming[0].purchase_order_id)
    assert ours.xero_tenant_id == RUN_TENANT
