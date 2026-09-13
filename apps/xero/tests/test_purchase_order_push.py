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
from unittest.mock import patch
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
from apps.xero.sync import sync_local_purchase_orders_to_xero
from apps.xero.tests.conftest import make_po_manager, make_po_provider

MIRROR = "apps.purchasing.services.accounting_mirror.get_provider"

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


def test_hourly_push_cannot_clear_a_newer_failed_transition(office_staff: Staff) -> None:
    """An acknowledgement belongs to the version that was sent.

    The hourly sync holds no lock across the vendor call. An operator deletes
    the order while its SUBMITTED push is in flight; that transition is refused
    by a 429 and left owed. The older push then completes. The flag it clears
    must be the one it earned, or the newer transition is never sent: locally
    deleted, submitted in Xero, and nothing left for the hourly sync to find.
    """
    po = make_purchase_order(created_by=office_staff, status="submitted", xero_id=uuid4())
    make_po_line(po)
    PurchaseOrder.objects.filter(pk=po.pk).update(xero_push_due=True)
    success = DocumentResult(success=True, external_id=str(po.xero_id), document_status="SUBMITTED")
    transport = make_po_provider(success)

    def edit_during_send(payload: POPayload) -> DocumentResult:
        assert payload.status == "SUBMITTED"
        current = PurchaseOrder.objects.get(pk=po.pk)
        with patch(MIRROR) as unavailable:
            unavailable.return_value.push_purchase_order.return_value = DocumentResult(
                success=False, status_code=429, error="Later request refused"
            )
            changed = update_purchase_order(
                current.id,
                {"status": "deleted"},
                staff=office_staff,
                if_match=purchase_order_etag(current),
            )
            assert changed.xero_push_due
        return success

    transport.update_purchase_order.side_effect = edit_during_send

    def real_manager(order: PurchaseOrder, _staff: Staff) -> DocumentResult:
        result = make_po_manager(order, transport).sync_to_xero()
        return DocumentResult(success=result["success"])

    with (
        patch(MIRROR) as provider,
        patch("apps.xero.sync.quota_floor_breached", return_value=False),
        patch("apps.xero.documents.po.get_tenant_id", return_value=str(uuid4())),
    ):
        provider.return_value.push_purchase_order.side_effect = real_manager
        list(sync_local_purchase_orders_to_xero())

    po.refresh_from_db()
    assert po.status == "deleted"
    assert po.xero_push_due, "the older push acknowledged the newer unsent transition"


def test_deferred_return_to_draft_is_retried(office_staff: Staff) -> None:
    """Owing a call is a boolean the transition sets; the selector does not second-guess it.

    Returning an order to draft is Xero learning it was pulled. When that push
    is refused by a 429 the order stays owed, and the hourly sync must send it
    like any other transition: excluding drafts there left the Xero copy
    submitted for good.
    """
    po = make_purchase_order(created_by=office_staff, status="submitted", xero_id=uuid4())
    make_po_line(po)
    with patch(MIRROR) as provider:
        provider.return_value.push_purchase_order.return_value = DocumentResult(
            success=False, status_code=429, error="Quota exhausted"
        )
        po = update_purchase_order(
            po.id, {"status": "draft"}, staff=office_staff, if_match=purchase_order_etag(po)
        )
        assert po.xero_push_due
        provider.return_value.push_purchase_order.reset_mock()
        provider.return_value.push_purchase_order.return_value = DocumentResult(success=True)
        with patch("apps.xero.sync.quota_floor_breached", return_value=False):
            list(sync_local_purchase_orders_to_xero())
        provider.return_value.push_purchase_order.assert_called_once()
    po.refresh_from_db()
    assert not po.xero_push_due
