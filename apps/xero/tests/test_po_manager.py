"""The purchase-order push path: manager routing, persistence, and endpoint.

Business risk covered: no E2E spec exercises PO push, so these tests are its
only gate. The expensive failure modes are silent — storing Xero's zero-UUID
sentinel as a real id, pushing a PO whose supplier was never synced, or
mismatching line-item ids so receipts later reconcile against the wrong line.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import Mock, patch

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounting.types import DocumentResult
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.xero.constants import ZERO_UUID
from apps.xero.documents.po import XeroPurchaseOrderManager

pytestmark = pytest.mark.django_db


@pytest.fixture
def supplier() -> Company:
    return Company.objects.create(
        name="Test Supplier",
        xero_contact_id="00000000-0000-0000-0000-000000000001",
        xero_last_modified=timezone.now(),
    )


@pytest.fixture
def po(supplier: Company) -> PurchaseOrder:
    order = PurchaseOrder.objects.create(supplier=supplier, po_number="PO-TEST-0001")
    PurchaseOrderLine.objects.create(
        purchase_order=order,
        description="Steel plate",
        quantity=Decimal("2"),
        unit_cost=Decimal("50.00"),
    )
    return order


@pytest.fixture
def job(supplier: Company) -> Job:
    """A job to bind a PO line to, so the Xero description carries its number."""
    return make_job(supplier, Staff.get_automation_user(), name="Tank repair")


def _manager(po: PurchaseOrder, provider: Mock) -> XeroPurchaseOrderManager:
    with patch("apps.xero.documents.base.get_provider", return_value=provider):
        return XeroPurchaseOrderManager(purchase_order=po, staff=Staff.get_automation_user())


def _provider(result: DocumentResult | None = None) -> Mock:
    provider = Mock()
    provider.get_account_code.return_value = "300"
    if result is not None:
        provider.create_purchase_order.return_value = result
        provider.update_purchase_order.return_value = result
    return provider


class TestSyncRouting:
    def test_create_path_stores_xero_data(self, po: PurchaseOrder, xero_tenant_id: str) -> None:
        external_id = str(uuid.uuid4())
        provider = _provider(
            DocumentResult(
                success=True,
                external_id=external_id,
                number=po.po_number,
                online_url=f"https://go.xero.com/Accounts/Payable/PurchaseOrders/Edit/{external_id}/",
                raw_response={"line_items": []},
            )
        )

        result = _manager(po, provider).sync_to_xero()

        assert result["success"]
        provider.create_purchase_order.assert_called_once()
        provider.update_purchase_order.assert_not_called()
        po.refresh_from_db()
        assert str(po.xero_id) == external_id
        # The tenant is written with the id, never separately: an id with no
        # tenant cannot be attributed to an org.
        assert po.xero_tenant_id == xero_tenant_id
        assert po.online_url is not None and external_id in po.online_url

    def test_existing_xero_id_routes_to_update(self, po: PurchaseOrder) -> None:
        existing_id = str(uuid.uuid4())
        po.xero_id = existing_id
        po.save(update_fields=["xero_id"])
        provider = _provider(DocumentResult(success=True, external_id=existing_id, raw_response={}))

        result = _manager(po, provider).sync_to_xero()

        assert result["success"]
        provider.update_purchase_order.assert_called_once()
        provider.create_purchase_order.assert_not_called()
        payload = provider.update_purchase_order.call_args.args[0]
        assert payload.external_id == existing_id

    def test_zero_uuid_is_treated_as_unsynced(self, po: PurchaseOrder) -> None:
        """The zero-UUID sentinel must route to create, never update."""
        po.xero_id = ZERO_UUID
        po.save(update_fields=["xero_id"])
        provider = _provider(
            DocumentResult(success=True, external_id=str(uuid.uuid4()), raw_response={})
        )

        manager = _manager(po, provider)
        assert manager.get_xero_id() is None
        manager.sync_to_xero()
        provider.create_purchase_order.assert_called_once()

    def test_provider_failure_becomes_api_error(self, po: PurchaseOrder) -> None:
        provider = _provider(
            DocumentResult(success=False, error="Rate limit exceeded", status_code=429)
        )

        result = _manager(po, provider).sync_to_xero()

        assert not result["success"]
        assert result["error_type"] == "api_error"
        assert result["status"] == 429
        po.refresh_from_db()
        assert po.xero_id is None


class TestValidation:
    def test_po_without_lines_refuses_sync(self, supplier: Company) -> None:
        empty_po = PurchaseOrder.objects.create(supplier=supplier, po_number="PO-TEST-0002")
        provider = _provider()

        result = _manager(empty_po, provider).sync_to_xero()

        assert not result["success"]
        assert result["error_type"] == "validation_error"
        assert result["status"] == 400
        provider.create_purchase_order.assert_not_called()

    def test_unsynced_supplier_refuses_sync(self, supplier: Company, po: PurchaseOrder) -> None:
        supplier.xero_contact_id = None
        supplier.save(update_fields=["xero_contact_id"])
        po.refresh_from_db()
        provider = _provider()

        result = _manager(po, provider).sync_to_xero()

        assert not result["success"]
        assert result["error_type"] == "validation_error"
        assert "not linked to Xero" in str(result["error"])
        provider.create_purchase_order.assert_not_called()

    def test_missing_supplier_fails_construction(self) -> None:
        orphan = PurchaseOrder.objects.create(po_number="PO-TEST-0003")
        with pytest.raises(ValueError, match="supplier"):
            _manager(orphan, _provider())


class TestLineItemBackfill:
    def test_duplicate_descriptions_claim_distinct_lines(self, supplier: Company) -> None:
        """Two identical descriptions must map to two different Xero line ids."""
        order = PurchaseOrder.objects.create(supplier=supplier, po_number="PO-TEST-0004")
        line_a = PurchaseOrderLine.objects.create(
            purchase_order=order,
            description="Widget",
            quantity=Decimal("1"),
            unit_cost=Decimal("10.00"),
        )
        line_b = PurchaseOrderLine.objects.create(
            purchase_order=order,
            description="Widget",
            quantity=Decimal("3"),
            unit_cost=Decimal("10.00"),
        )
        id_one, id_two = str(uuid.uuid4()), str(uuid.uuid4())
        raw: dict[str, Any] = {
            "line_items": [
                {"line_item_id": id_one, "description": "Widget"},
                {"line_item_id": id_two, "description": "Widget"},
            ]
        }
        provider = _provider(
            DocumentResult(success=True, external_id=str(uuid.uuid4()), raw_response=raw)
        )

        _manager(order, provider).sync_to_xero()

        line_a.refresh_from_db()
        line_b.refresh_from_db()
        assert {str(line_a.xero_line_item_id), str(line_b.xero_line_item_id)} == {id_one, id_two}


class TestDelete:
    def test_delete_clears_local_state(self, po: PurchaseOrder) -> None:
        external_id = str(uuid.uuid4())
        po.xero_id = external_id
        po.xero_tenant_id = "some-tenant"
        po.save(update_fields=["xero_id", "xero_tenant_id"])
        provider = _provider()
        provider.delete_purchase_order.return_value = DocumentResult(
            success=True, external_id=external_id
        )

        result = _manager(po, provider).delete_document()

        assert result["success"]
        po.refresh_from_db()
        assert po.xero_id is None
        # Cleared with the id, for the same reason it is written with it: a
        # tenant claim on a row that links to nothing is a lie.
        assert po.xero_tenant_id is None
        assert po.status == "deleted"

    def test_delete_without_xero_id_is_404(self, po: PurchaseOrder) -> None:
        provider = _provider()

        result = _manager(po, provider).delete_document()

        assert not result["success"]
        assert result["status"] == 404
        provider.delete_purchase_order.assert_not_called()


class TestEndpoint:
    def test_create_endpoint_reaches_manager(self, api: Client, po: PurchaseOrder) -> None:
        """The endpoint constructs the manager with the request's staff and
        returns the manager's outcome — the wiring v1 shipped broken (its
        PO views missed the staff argument and 500'd on every push).
        """
        with (
            patch("apps.xero.api.get_valid_token", return_value={"access_token": "t"}),
            patch.object(
                XeroPurchaseOrderManager,
                "sync_to_xero",
                return_value={
                    "success": True,
                    "xero_id": str(uuid.uuid4()),
                    "online_url": "https://go.xero.com/example",
                },
            ) as mock_sync,
            patch("apps.xero.documents.base.get_provider", return_value=_provider()),
        ):
            response = api.post(f"/api/xero/create_purchase_order/{po.id}")

        assert response.status_code == 200, response.content
        mock_sync.assert_called_once()

    def test_unknown_po_is_404(self, api: Client) -> None:
        with patch("apps.xero.api.get_valid_token", return_value={"access_token": "t"}):
            response = api.post(f"/api/xero/create_purchase_order/{uuid.uuid4()}")
        assert response.status_code == 404


class TestPayload:
    """What we actually send Xero.

    The integration suite proved this payload is one Xero accepts
    (apps/xero/tests/test_purchase_order_integration.py). These pin the parts
    that could drift back without any fake noticing — the payroll failure ADR
    0050 cites was exactly a payload-shape bug that passed a full fake suite.
    """

    def test_the_payload_carries_what_xero_accepted(self, po: PurchaseOrder) -> None:
        po.reference = "Job 1234 steel"
        po.expected_delivery = date(2026, 12, 24)
        po.save(update_fields=["reference", "expected_delivery"])
        provider = _provider()

        payload = _manager(po, provider).build_payload()

        assert payload.supplier_external_id == "00000000-0000-0000-0000-000000000001"
        assert payload.po_number == "PO-TEST-0001"
        assert payload.reference == "Job 1234 steel"
        assert payload.delivery_date == date(2026, 12, 24)
        assert payload.status == "DRAFT"
        assert payload.external_id is None, "a first push must not claim an existing document"
        line = payload.line_items[0]
        assert line.description == "Steel plate"
        assert line.quantity == Decimal("2")
        assert line.unit_amount == Decimal("50.00")
        assert line.item_code is None, "an unset item code reaches Xero as null, not ''"

    def test_lines_are_costed_to_the_purchases_account(self, po: PurchaseOrder) -> None:
        """The account name is asked for by name, and it is not Sales.

        A drift to the sales account would book every purchase as revenue and
        say nothing: the push still succeeds, because Xero accepts any code we
        send it.
        """
        provider = _provider()

        payload = _manager(po, provider).build_payload()

        provider.get_account_code.assert_called_once_with("Purchases")
        assert payload.line_items[0].account_code == "300"

    def test_an_unpriced_line_costs_zero_rather_than_null(self, supplier: Company) -> None:
        """Xero requires a number; None would be rejected for the whole order."""
        order = PurchaseOrder.objects.create(supplier=supplier, po_number="PO-TEST-0002")
        PurchaseOrderLine.objects.create(
            purchase_order=order, description="TBC", quantity=Decimal("1"), unit_cost=None
        )

        payload = _manager(order, _provider()).build_payload()

        assert payload.line_items[0].unit_amount == Decimal("0")

    def test_a_job_line_tells_the_supplier_which_job_it_is_for(
        self, po: PurchaseOrder, job: Job
    ) -> None:
        """The job number is what the supplier reads on the delivery."""
        line = po.po_lines.get()
        line.job = job
        line.save(update_fields=["job"])

        payload = _manager(po, _provider()).build_payload()

        assert payload.line_items[0].description == f"{job.job_number} - Steel plate"

    @pytest.mark.parametrize(
        ("local_status", "xero_status"),
        [
            ("draft", "DRAFT"),
            ("submitted", "SUBMITTED"),
            ("partially_received", "AUTHORISED"),
            ("fully_received", "AUTHORISED"),
        ],
    )
    def test_receiving_states_both_map_to_authorised(
        self, po: PurchaseOrder, local_status: str, xero_status: str
    ) -> None:
        """Xero has no notion of partial receipt, so both of ours collapse."""
        po.status = local_status
        po.save(update_fields=["status"])

        assert _manager(po, _provider()).build_payload().status == xero_status


class TestStateGate:
    """Which orders may be pushed at all."""

    def test_a_draft_may_be_created_in_xero(self, po: PurchaseOrder) -> None:
        assert _manager(po, _provider()).state_valid_for_xero() is True

    def test_a_submitted_order_cannot_be_created_in_xero(self, po: PurchaseOrder) -> None:
        """Creating from a non-draft would push an order the supplier already has."""
        po.status = "submitted"
        po.save(update_fields=["status"])

        assert _manager(po, _provider()).state_valid_for_xero() is False

    def test_an_already_synced_order_may_be_updated_at_any_status(self, po: PurchaseOrder) -> None:
        """Receiving changes an order after submission; those changes must still push."""
        po.status = "fully_received"
        po.xero_id = uuid.uuid4()
        po.save(update_fields=["status", "xero_id"])

        assert _manager(po, _provider()).state_valid_for_xero() is True
