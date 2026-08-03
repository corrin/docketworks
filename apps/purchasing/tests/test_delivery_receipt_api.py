"""API tests for the delivery-receipt flow.

Covers the receipt's business effects (received quantities → Stock rows /
material CostLines, PO status recompute) and the ADR 0003 precondition on an
endpoint whose resource id lives in the request BODY rather than the URL.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import PurchaseOrder, Stock
from apps.purchasing.tests.conftest import make_po_line, make_purchase_order

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.purchasing.tests.urls"),
]

RECEIPTS_URL = "/api/purchasing/delivery-receipts/"


def _po_etag(client: Client, po: PurchaseOrder) -> str:
    response = client.get(f"/api/purchasing/purchase-orders/{po.id}/")
    assert response.status_code == 200
    return response.headers["ETag"]


def _post_receipt(
    client: Client,
    po: PurchaseOrder,
    allocations: Mapping[str, Mapping[str, object]],
    *,
    if_match: str | None,
) -> "_MonkeyPatchedWSGIResponse":
    headers = {"If-Match": if_match} if if_match is not None else {}
    return client.post(
        RECEIPTS_URL,
        data={"purchase_order_id": str(po.id), "allocations": allocations},
        content_type="application/json",
        headers=headers,
    )


@pytest.mark.usefixtures("company_defaults")
class TestDeliveryReceiptConcurrency:
    """ADR 0003 with the PO id in the body (frontend interceptor special case)."""

    def test_missing_if_match_is_428_and_writes_nothing(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="4.00")

        response = _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "4",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "4"}],
                }
            },
            if_match=None,
        )

        assert response.status_code == 428
        line.refresh_from_db()
        assert line.received_quantity == Decimal("0.00")
        assert not Stock.objects.filter(source="purchase_order").exists()

    def test_stale_if_match_is_412_and_writes_nothing(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="4.00")
        stale = _po_etag(client, po)
        PurchaseOrder.objects.filter(pk=po.pk).update(
            reference="Concurrent edit", updated_at=timezone.now()
        )

        response = _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "4",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "4"}],
                }
            },
            if_match=stale,
        )

        assert response.status_code == 412
        line.refresh_from_db()
        assert line.received_quantity == Decimal("0.00")
        assert not Stock.objects.filter(source="purchase_order").exists()

    def test_replaying_a_consumed_etag_is_412(self, client: Client, stock_holding_job: Job) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="4.00")
        etag = _po_etag(client, po)
        allocations: Mapping[str, Mapping[str, object]] = {
            str(line.id): {
                "total_received": "2",
                "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "2"}],
            }
        }

        first = _post_receipt(client, po, allocations, if_match=etag)
        second = _post_receipt(client, po, allocations, if_match=etag)

        assert first.status_code == 200
        assert second.status_code == 412
        line.refresh_from_db()
        # Exactly one receipt applied — double submission produced no duplicate.
        assert line.received_quantity == Decimal("2.00")

    def test_success_returns_the_refreshed_etag(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="4.00")
        etag = _po_etag(client, po)

        response = _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "4",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "4"}],
                }
            },
            if_match=etag,
        )

        assert response.status_code == 200
        assert response.json() == {"success": True, "error": None}
        assert response.headers["ETag"] != etag


@pytest.mark.usefixtures("company_defaults")
class TestDeliveryReceiptEffects:
    def test_stock_allocation_creates_a_stock_row_from_the_line(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(
            po,
            quantity="10.00",
            unit_cost="25.00",
            description="50x50 SHS",
            metal_type="mild_steel",
        )

        response = _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "10",
                    "allocations": [
                        {
                            "job_id": str(stock_holding_job.id),
                            "quantity": "10",
                            "metadata": {"location": "Rack 3", "alloy": "350"},
                        }
                    ],
                }
            },
            if_match=_po_etag(client, po),
        )

        assert response.status_code == 200
        stock = Stock.objects.get(source="purchase_order")
        assert stock.description == "50x50 SHS"
        assert stock.quantity == Decimal("10.00")
        assert stock.unit_cost == Decimal("25.00")
        # 20% company markup applied to the stock's revenue.
        assert stock.unit_revenue == Decimal("30.00")
        assert stock.location == "Rack 3"
        assert stock.alloy == "350"
        # Metadata the caller omitted falls back to the PO line's own values.
        assert stock.metal_type == "mild_steel"
        assert stock.source_purchase_order_line_id == line.id

    def test_an_explicitly_blanked_metadata_field_is_cleared(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        """Blank is an instruction, not a gap.

        v1 read metadata as ``metadata.get(field, line.field) or None``: an
        absent key inherits the PO line, a key present-but-blank means the
        operator cleared it. Collapsing the two hands a cleared field back the
        value that was ordered.
        """
        po = make_purchase_order(status="submitted")
        line = make_po_line(
            po,
            quantity="1.00",
            metal_type="mild_steel",
            alloy="350",
            specifics="ordered spec",
            location="Ordered rack",
        )

        _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "1",
                    "allocations": [
                        {
                            "job_id": str(stock_holding_job.id),
                            "quantity": "1",
                            "metadata": {
                                "metal_type": "",
                                "alloy": "",
                                "specifics": "",
                                "location": "",
                            },
                        }
                    ],
                }
            },
            if_match=_po_etag(client, po),
        )

        stock = Stock.objects.get(source="purchase_order")
        assert stock.metal_type is None
        assert stock.alloy is None
        assert stock.specifics is None
        assert stock.location is None

    def test_metadata_omitted_entirely_inherits_every_line_value(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(
            po,
            quantity="1.00",
            metal_type="mild_steel",
            alloy="350",
            specifics="ordered spec",
            location="Ordered rack",
        )

        _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "1",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "1"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        stock = Stock.objects.get(source="purchase_order")
        assert stock.metal_type == "mild_steel"
        assert stock.alloy == "350"
        assert stock.specifics == "ordered spec"
        assert stock.location == "Ordered rack"

    def test_job_allocation_creates_a_material_cost_line(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        job: Job,
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="4.00", unit_cost="50.00", description="Plate")

        _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "4",
                    "allocations": [{"job_id": str(job.id), "quantity": "4"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        cost_line = CostLine.objects.get(kind="material", cost_set__job=job)
        assert cost_line.quantity == Decimal("4.000")
        assert cost_line.unit_cost == Decimal("50.00")
        assert cost_line.unit_rev == Decimal("60.00")
        assert cost_line.ext_refs["purchase_order_id"] == str(po.id)
        assert cost_line.ext_refs["purchase_order_line_id"] == str(line.id)
        assert cost_line.meta["source"] == "delivery_receipt"

    def test_a_custom_retail_rate_is_honoured(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        job: Job,
    ) -> None:
        # v1 read this override under "retailRate" while its serializer emitted
        # "retail_rate", so every custom markup was silently discarded.
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="1.00", unit_cost="100.00")

        _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "1",
                    "allocations": [
                        {"job_id": str(job.id), "quantity": "1", "retail_rate": "50.00"}
                    ],
                }
            },
            if_match=_po_etag(client, po),
        )

        cost_line = CostLine.objects.get(kind="material", cost_set__job=job)
        assert cost_line.unit_rev == Decimal("150.00")

    def test_partial_receipt_moves_the_po_to_partially_received(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="10.00")

        _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "4",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "4"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        po.refresh_from_db()
        assert po.status == "partially_received"
        line.refresh_from_db()
        assert line.received_quantity == Decimal("4.00")

    def test_full_receipt_moves_the_po_to_fully_received(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="10.00")

        _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "10",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "10"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        po.refresh_from_db()
        assert po.status == "fully_received"

    def test_re_receipting_a_line_replaces_stock_but_accumulates_received(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        """PORTED v1 DEBT, not intended design — see the parity ledger.

        Re-receipting deletes the line's prior stock rows but ADDS to
        received_quantity, so a line received twice can read fully_received
        while only the last receipt's stock exists. Stock and books disagree.
        Recorded rather than fixed because changing it would silently alter
        received totals on migrated data; the fix belongs with a deliberate
        stock-reconciliation decision.
        """
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="10.00")
        allocation: Mapping[str, Mapping[str, object]] = {
            str(line.id): {
                "total_received": "3",
                "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "3"}],
            }
        }

        _post_receipt(client, po, allocation, if_match=_po_etag(client, po))
        _post_receipt(client, po, allocation, if_match=_po_etag(client, po))

        # One stock row survives (the prior one was deleted) but the received
        # total counted both receipts — that is the divergence being recorded.
        assert Stock.objects.filter(source="purchase_order").count() == 1
        line.refresh_from_db()
        assert line.received_quantity == Decimal("6.00")


@pytest.mark.usefixtures("company_defaults")
class TestDeliveryReceiptValidation:
    def test_allocation_total_must_match_the_received_total(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="10.00")

        response = _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "10",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "4"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        assert response.status_code == 400
        assert "Allocation mismatch" in response.json()["detail"]
        line.refresh_from_db()
        assert line.received_quantity == Decimal("0.00")

    def test_a_price_tbc_line_cannot_be_received(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="10.00", unit_cost=None, price_tbc=True)

        response = _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "10",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "10"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        assert response.status_code == 400
        assert "Price not confirmed" in response.json()["detail"]

    def test_a_draft_purchase_order_cannot_be_received(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="draft")
        line = make_po_line(po, quantity="10.00")

        response = _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "10",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "10"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        assert response.status_code == 400
        assert "with status 'draft'" in response.json()["detail"]

    def test_a_line_from_another_po_is_rejected(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        other_line = make_po_line(make_purchase_order(status="submitted"))

        response = _post_receipt(
            client,
            po,
            {
                str(other_line.id): {
                    "total_received": "1",
                    "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "1"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        assert response.status_code == 400
        assert "mismatched PurchaseOrderLine IDs" in response.json()["detail"]

    def test_an_unknown_job_is_rejected(self, client: Client, stock_holding_job: Job) -> None:  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="1.00")

        response = _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "1",
                    "allocations": [{"job_id": str(uuid4()), "quantity": "1"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        assert response.status_code == 400
        assert "Invalid Job IDs" in response.json()["detail"]

    def test_shop_jobs_are_never_billed(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        company_defaults: CompanyDefaults,
        office_staff: Staff,
    ) -> None:
        shop_job = make_job(company_defaults.shop_company, office_staff, name="Shop work")
        assert shop_job.shop_job
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="1.00", unit_cost="100.00")

        _post_receipt(
            client,
            po,
            {
                str(line.id): {
                    "total_received": "1",
                    "allocations": [{"job_id": str(shop_job.id), "quantity": "1"}],
                }
            },
            if_match=_po_etag(client, po),
        )

        cost_line = CostLine.objects.get(kind="material", cost_set__job=shop_job)
        assert cost_line.unit_rev == Decimal("0.00")
