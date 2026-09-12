"""A push may only claim the local line identities it actually sent.

Xero answers a write by echoing the order it stored, and the echo carries a
line id per description. Matching those back onto local lines is the only way a
later update can address the same line rather than replacing it, so a mismatch
is silent and permanent: the line keeps working and points at the wrong
document row.

Business risk covered. An edit can land between building the payload and the
response arriving, so the echo describes a line that no longer exists. Attaching
its id to whatever now holds that description would hand a replacement line the
identity of the line it replaced (ADR 0057), and duplicate descriptions on one
order make the same mistake available twice over.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.accounting.types import DocumentResult, POPayload
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.purchasing.etag import purchase_order_etag
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services.purchase_order_service import update_purchase_order
from apps.purchasing.tests.factories import make_po_line, make_purchase_order
from apps.xero.tests.conftest import make_po_manager, make_po_provider

pytestmark = pytest.mark.django_db


@pytest.fixture
def pushable_po(office_staff: Staff) -> PurchaseOrder:
    supplier = Company.objects.create(
        name="Push supplier", xero_contact_id=str(uuid4()), xero_last_modified=timezone.now()
    )
    po = make_purchase_order(
        supplier=supplier, created_by=office_staff, status="submitted", reference="Original"
    )
    make_po_line(po)
    return po


def test_response_cannot_attach_an_old_line_id_to_a_replacement(
    pushable_po: PurchaseOrder, office_staff: Staff
) -> None:
    po = pushable_po
    original = po.po_lines.get()
    response_id = uuid4()
    external_id = str(uuid4())
    success = DocumentResult(
        success=True,
        external_id=external_id,
        raw_response={
            "line_items": [
                {"description": original.xero_description, "line_item_id": str(response_id)}
            ]
        },
    )
    provider = make_po_provider(success)

    def replace_while_sending(payload: POPayload) -> DocumentResult:
        assert payload.line_items[0].description == original.xero_description
        update_purchase_order(
            po.id,
            {
                "lines_to_delete": [original.id],
                "lines": [
                    {
                        "description": original.description,
                        "quantity": Decimal("2"),
                        "unit_cost": Decimal("19"),
                    }
                ],
            },
            staff=office_staff,
            if_match=purchase_order_etag(po),
        )
        return success

    provider.create_purchase_order.side_effect = replace_while_sending
    assert make_po_manager(po, provider).sync_to_xero()["success"]
    replacement = po.po_lines.get()
    po.refresh_from_db()
    assert replacement.id != original.id
    assert replacement.xero_line_item_id is None, "a replacement inherited the id it replaced"
    assert str(po.xero_id) == external_id
    assert replacement.unit_cost == Decimal("19")


def test_push_snapshot_refreshes_header_and_lines_together(
    pushable_po: PurchaseOrder, office_staff: Staff
) -> None:
    po = pushable_po
    provider = make_po_provider(DocumentResult(success=True, external_id=str(uuid4())))
    manager = make_po_manager(po, provider)
    original = po.po_lines.get()
    updated = update_purchase_order(
        po.id,
        {"reference": "New header", "lines": [{"id": original.id, "unit_cost": Decimal("19")}]},
        staff=office_staff,
        if_match=purchase_order_etag(po),
    )
    assert manager.sync_to_xero()["success"]
    payload = provider.create_purchase_order.call_args.args[0]
    assert payload.reference == "New header"
    assert payload.line_items[0].unit_amount == Decimal("19")
    po.refresh_from_db()
    assert po.updated_at == updated.updated_at, "the push must not bump the row's ETag"


def test_duplicate_descriptions_receive_distinct_response_line_ids(
    pushable_po: PurchaseOrder,
) -> None:
    po = pushable_po
    original = po.po_lines.get()
    make_po_line(
        po,
        description=original.description,
        quantity=str(original.quantity),
        unit_cost=str(original.unit_cost),
    )
    response_ids = [uuid4(), uuid4()]
    success = DocumentResult(
        success=True,
        external_id=str(uuid4()),
        raw_response={
            "line_items": [
                {"description": original.xero_description, "line_item_id": str(line_id)}
                for line_id in response_ids
            ]
        },
    )
    assert make_po_manager(po, make_po_provider(success)).sync_to_xero()["success"]
    assert set(po.po_lines.values_list("xero_line_item_id", flat=True)) == set(response_ids)
