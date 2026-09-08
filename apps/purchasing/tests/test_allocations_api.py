"""API tests for PO allocations: listing, details, reversal, auto-allocation."""

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import PurchaseOrder, Stock, StockMovement
from apps.purchasing.tests.factories import make_po_line, make_purchase_order

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.purchasing.tests.urls"),
]

PO_URL = "/api/purchasing/purchase-orders/"


def _receipt(client: Client, po: PurchaseOrder, line_id: str, job_id: str, quantity: str) -> None:
    etag = client.get(f"{PO_URL}{po.id}/").headers["ETag"]
    response = client.post(
        "/api/purchasing/delivery-receipts/",
        data={
            "purchase_order_id": str(po.id),
            "allocations": {
                line_id: {
                    "total_received": quantity,
                    "allocations": [{"job_id": job_id, "quantity": quantity}],
                }
            },
        },
        content_type="application/json",
        headers={"If-Match": etag},
    )
    assert response.status_code == 200


@pytest.mark.usefixtures("company_defaults")
class TestAllocationListing:
    def test_lists_stock_and_job_allocations_by_line(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        stock_line = make_po_line(po, quantity="5.00", description="To stock")
        job_line = make_po_line(po, quantity="3.00", description="To job")
        _receipt(client, po, str(stock_line.id), str(stock_holding_job.id), "5")
        _receipt(client, po, str(job_line.id), str(job.id), "3")

        body = client.get(f"{PO_URL}{po.id}/allocations/").json()

        assert body["po_id"] == str(po.id)
        stock_alloc = body["allocations"][str(stock_line.id)][0]
        assert stock_alloc["type"] == "stock"
        # The stock-holding job is displayed as "Stock", not by its job name.
        assert stock_alloc["job_name"] == "Stock"
        assert stock_alloc["quantity"] == 5.0
        assert stock_alloc["retail_rate"] == 20.0
        job_alloc = body["allocations"][str(job_line.id)][0]
        assert job_alloc["type"] == "job"
        assert job_alloc["job_name"] == job.name
        assert job_alloc["quantity"] == 3.0

    def test_a_purchase_order_without_allocations_reports_none(self, client: Client) -> None:
        po = make_purchase_order()
        assert client.get(f"{PO_URL}{po.id}/allocations/").json()["allocations"] == {}


@pytest.mark.usefixtures("company_defaults")
class TestTheDetailsReadTakesNoLock:
    """A GET must not take a row lock, and the SQL is the only honest witness.

    ``select_for_update`` is legal inside a transaction and raises
    ``TransactionManagementError`` in autocommit. There is no
    ``ATOMIC_REQUESTS`` in ``config/``, so locking here is a 500 in production —
    yet every test in this file passes, because pytest wraps each one in a
    transaction. The usual escape, ``django_db(transaction=True)``, is closed
    on purpose: this project refuses Django's ``flush`` (ADR 0048), which that
    mode needs for teardown. So the request is made normally and the emitted
    SQL is inspected instead, which pins the property rather than the symptom.
    """

    def test_no_statement_locks_a_row(self, client: Client, stock_holding_job: Job) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="5.00", description="Bar", location="Rack 2")
        _receipt(client, po, str(line.id), str(stock_holding_job.id), "5")
        stock = Stock.objects.get(source="purchase_order")

        with CaptureQueriesContext(connection) as queries:
            response = client.get(f"{PO_URL}{po.id}/allocations/stock/{stock.id}/details/")

        assert response.status_code == 200
        locking = [q["sql"] for q in queries.captured_queries if "FOR UPDATE" in q["sql"].upper()]
        assert locking == [], "a read path took a row lock; in production this is a 500"


@pytest.mark.usefixtures("company_defaults")
class TestAllocationDetails:
    def test_stock_allocation_details_report_reversal_eligibility(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="5.00", description="Bar", location="Rack 2")
        _receipt(client, po, str(line.id), str(stock_holding_job.id), "5")
        stock = Stock.objects.get(source="purchase_order")

        body = client.get(f"{PO_URL}{po.id}/allocations/stock/{stock.id}/details/").json()

        assert body["type"] == "stock"
        assert body["quantity"] == 5.0
        assert body["can_reverse"] is True
        assert body["consumed_by_jobs"] == 0
        assert body["location"] == "Rack 2"

    def test_consumed_stock_can_be_corrected_without_erasing_job_history(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="5.00")
        _receipt(client, po, str(line.id), str(stock_holding_job.id), "5")
        stock = Stock.objects.get(source="purchase_order")
        client.post(
            f"/api/purchasing/stock/{stock.id}/consume/",
            data={"job_id": str(job.id), "quantity": "1"},
            content_type="application/json",
        )

        body = client.get(f"{PO_URL}{po.id}/allocations/stock/{stock.id}/details/").json()

        assert body["can_reverse"] is True
        assert body["consumed_by_jobs"] == 1

    def test_job_allocation_details_report_the_rates(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        job: Job,
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="2.00", unit_cost="50.00")
        _receipt(client, po, str(line.id), str(job.id), "2")
        cost_line = CostLine.objects.get(kind="material", cost_set__job=job)

        body = client.get(f"{PO_URL}{po.id}/allocations/job/{cost_line.id}/details/").json()

        assert body["type"] == "job"
        assert body["unit_cost"] == 50.0
        assert body["unit_revenue"] == 60.0
        assert body["can_reverse"] is True

    def test_an_unknown_allocation_type_is_400(self, client: Client) -> None:
        po = make_purchase_order()
        response = client.get(f"{PO_URL}{po.id}/allocations/bogus/{uuid4()}/details/")
        assert response.status_code == 400

    def test_an_allocation_from_another_po_is_404(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        other = make_purchase_order(status="submitted")
        line = make_po_line(other, quantity="1.00")
        _receipt(client, other, str(line.id), str(stock_holding_job.id), "1")
        stock = Stock.objects.get(source="purchase_order")

        response = client.get(f"{PO_URL}{po.id}/allocations/stock/{stock.id}/details/")

        assert response.status_code == 404


@pytest.mark.usefixtures("company_defaults")
class TestAllocationReversal:
    @pytest.mark.parametrize("allocation_type", ["stock", "job"])
    def test_lost_response_retry_reports_already_reversed_without_writes(
        self, client: Client, stock_holding_job: Job, job: Job, allocation_type: str
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="2.00")
        destination = stock_holding_job if allocation_type == "stock" else job
        _receipt(client, po, str(line.id), str(destination.id), "2")
        stock = Stock.objects.get(source_purchase_order_line=line)
        allocation_id = (
            stock.id if allocation_type == "stock" else CostLine.objects.get(cost_set__job=job).id
        )
        path = f"{PO_URL}{po.id}/lines/{line.id}/allocations/reverse/"
        payload = {"allocation_type": allocation_type, "allocation_id": str(allocation_id)}
        version = client.get(f"{PO_URL}{po.id}/").headers["ETag"]
        first = client.post(
            path, payload, content_type="application/json", headers={"If-Match": version}
        )
        assert first.status_code == 200, first.content
        assert first.json()["status"] == "reversed"
        stock.refresh_from_db()
        state = (StockMovement.objects.count(), CostLine.objects.count(), stock.inventory_version)

        second = client.post(
            path, payload, content_type="application/json", headers={"If-Match": version}
        )

        assert second.status_code == 200, second.content
        assert second.json()["status"] == "already_reversed"
        assert second.json()["reversed_quantity"] == 0
        assert second.headers["ETag"] == first.headers["ETag"]
        stock.refresh_from_db()
        line.refresh_from_db()
        assert (
            StockMovement.objects.count(),
            CostLine.objects.count(),
            stock.inventory_version,
        ) == state
        assert stock.quantity == 0
        assert line.received_quantity == 0
        details = client.get(
            f"{PO_URL}{po.id}/allocations/{allocation_type}/{allocation_id}/details/"
        ).json()
        assert details["can_reverse"] is False
        listed = client.get(f"{PO_URL}{po.id}/allocations/").json()["allocations"][str(line.id)]
        assert listed[0]["reversed"] is True

    def test_reversal_refuses_another_line_without_changing_the_receipt(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        source = make_po_line(po, quantity="2")
        other = make_po_line(po, quantity="2")
        _receipt(client, po, str(source.id), str(stock_holding_job.id), "2")
        stock = Stock.objects.get(source_purchase_order_line=source)
        response = self._reverse(client, po, str(other.id), "stock", str(stock.id))
        assert response.status_code == 400
        stock.refresh_from_db()
        source.refresh_from_db()
        assert stock.quantity == source.received_quantity == 2
        assert not StockMovement.objects.filter(kind="receipt_reversal").exists()

    def _reverse(
        self, client: Client, po: PurchaseOrder, line_id: str, alloc_type: str, alloc_id: str
    ) -> "_MonkeyPatchedWSGIResponse":
        """Reverse one allocation under the PO's current ETag.

        The precondition is fetched here rather than passed by every caller
        because these tests assert reversal behaviour; the two that own the
        precondition itself post directly, so the header they send is visible
        in the test.
        """
        return client.post(
            f"{PO_URL}{po.id}/lines/{line_id}/allocations/reverse/",
            data={"allocation_type": alloc_type, "allocation_id": alloc_id},
            content_type="application/json",
            headers={"If-Match": client.get(f"{PO_URL}{po.id}/").headers["ETag"]},
        )

    def test_reversing_without_if_match_is_428_and_writes_nothing(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="5.00", description="Bar")
        _receipt(client, po, str(line.id), str(stock_holding_job.id), "5")
        stock = Stock.objects.get(source="purchase_order")

        response = client.post(
            f"{PO_URL}{po.id}/lines/{line.id}/allocations/reverse/",
            data={"allocation_type": "stock", "allocation_id": str(stock.id)},
            content_type="application/json",
        )

        assert response.status_code == 428
        assert Stock.objects.filter(id=stock.id).exists()
        line.refresh_from_db()
        assert line.received_quantity == Decimal("5.00")

    def test_reversing_with_a_stale_if_match_is_412_and_writes_nothing(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="5.00", description="Bar")
        stale = client.get(f"{PO_URL}{po.id}/").headers["ETag"]
        # The receipt bumps the PO's updated_at, so the pre-receipt ETag is now
        # stale -- the state a second operator's open allocations list holds.
        _receipt(client, po, str(line.id), str(stock_holding_job.id), "5")
        stock = Stock.objects.get(source="purchase_order")

        response = client.post(
            f"{PO_URL}{po.id}/lines/{line.id}/allocations/reverse/",
            data={"allocation_type": "stock", "allocation_id": str(stock.id)},
            content_type="application/json",
            headers={"If-Match": stale},
        )

        assert response.status_code == 412
        assert Stock.objects.filter(id=stock.id).exists()
        line.refresh_from_db()
        assert line.received_quantity == Decimal("5.00")

    def test_reversing_a_stock_allocation_returns_the_quantity_to_the_line(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="5.00", description="Bar")
        _receipt(client, po, str(line.id), str(stock_holding_job.id), "5")
        stock = Stock.objects.get(source="purchase_order")

        body = self._reverse(client, po, str(line.id), "stock", str(stock.id)).json()

        assert body["status"] == "reversed"
        assert body["reversed_quantity"] == 5.0
        assert body["updated_received_quantity"] == 0.0
        stock.refresh_from_db()
        assert stock.quantity == 0
        line.refresh_from_db()
        assert line.received_quantity == Decimal("0.00")
        po.refresh_from_db()
        assert po.status == "submitted"

    def test_reversing_a_job_allocation_preserves_and_credits_the_cost_line(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        job: Job,
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="2.00")
        _receipt(client, po, str(line.id), str(job.id), "2")
        cost_line = CostLine.objects.get(kind="material", cost_set__job=job)

        body = self._reverse(client, po, str(line.id), "job", str(cost_line.id)).json()

        assert body["status"] == "reversed"
        assert body["job_name"] == job.name
        assert CostLine.objects.filter(id=cost_line.id).exists()
        assert (
            sum(row.quantity for row in CostLine.objects.filter(cost_set=cost_line.cost_set)) == 0
        )
        line.refresh_from_db()
        assert line.received_quantity == Decimal("0.00")

    def test_receipt_reversal_preserves_onward_issues_and_negative_stock(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="5.00")
        _receipt(client, po, str(line.id), str(stock_holding_job.id), "5")
        stock = Stock.objects.get(source="purchase_order")
        client.post(
            f"/api/purchasing/stock/{stock.id}/consume/",
            data={"job_id": str(job.id), "quantity": "1"},
            content_type="application/json",
        )

        response = self._reverse(client, po, str(line.id), "stock", str(stock.id))

        assert response.status_code == 200
        stock.refresh_from_db()
        assert stock.quantity == -1
        assert CostLine.objects.filter(cost_set__job=job, quantity=1).exists()
        assert Stock.objects.filter(id=stock.id).exists()

    def test_reversing_bumps_the_po_etag_even_when_the_status_is_unchanged(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        # v1's allocation path skipped the write when the status label matched,
        # leaving PO ETags stale after a reversal (the receipt path always bumped).
        po = make_purchase_order(status="submitted")
        first = make_po_line(po, quantity="5.00")
        second = make_po_line(po, quantity="5.00")
        _receipt(client, po, str(first.id), str(stock_holding_job.id), "2")
        _receipt(client, po, str(second.id), str(stock_holding_job.id), "2")
        before = client.get(f"{PO_URL}{po.id}/").headers["ETag"]
        stock = Stock.objects.filter(source_purchase_order_line=first).get()

        self._reverse(client, po, str(first.id), "stock", str(stock.id))

        po.refresh_from_db()
        assert po.status == "partially_received"
        assert client.get(f"{PO_URL}{po.id}/").headers["ETag"] != before

    def test_an_unknown_allocation_is_400(self, client: Client) -> None:
        po = make_purchase_order()
        line = make_po_line(po)

        response = self._reverse(client, po, str(line.id), "stock", str(uuid4()))

        assert response.status_code == 400
        assert "not found" in response.json()["detail"]


@pytest.mark.usefixtures("company_defaults")
class TestAutomaticAllocationOnFullyReceived:
    def test_setting_fully_received_allocates_unassigned_lines_to_stock(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="6.00", description="Auto to stock", job=None)
        etag = client.get(f"{PO_URL}{po.id}/").headers["ETag"]

        response = client.patch(
            f"{PO_URL}{po.id}/",
            data={"status": "fully_received"},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 200
        stock = Stock.objects.get(source="purchase_order")
        assert stock.quantity == Decimal("6.00")
        assert stock.job_id == stock_holding_job.id
        line.refresh_from_db()
        assert line.received_quantity == Decimal("6.00")

    def test_setting_fully_received_allocates_job_lines_to_cost_lines(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        job: Job,
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="3.00", unit_cost="10.00", job=job)
        etag = client.get(f"{PO_URL}{po.id}/").headers["ETag"]

        client.patch(
            f"{PO_URL}{po.id}/",
            data={"status": "fully_received"},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        cost_line = CostLine.objects.get(kind="material", cost_set__job=job)
        assert cost_line.quantity == Decimal("3.000")
        assert cost_line.unit_rev == Decimal("12.00")
        line.refresh_from_db()
        assert line.received_quantity == Decimal("3.00")

    def test_a_price_tbc_line_blocks_fully_received_with_a_400(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
    ) -> None:
        """Auto-allocation refuses a line whose price is still TBC.

        v2 added this guard; it raises ValueError, which the endpoint must map
        to 400 rather than let escape as a 500. v1 reached 400 for a stock line
        (ValueError out of Stock.retail_rate) but 500ed for a job line
        (TypeError multiplying a None unit cost) — v2 answers 400 for both.
        """
        po = make_purchase_order(status="submitted")
        make_po_line(po, quantity="2.00", unit_cost=None, price_tbc=True, job=None)
        etag = client.get(f"{PO_URL}{po.id}/").headers["ETag"]

        response = client.patch(
            f"{PO_URL}{po.id}/",
            data={"status": "fully_received"},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 400
        assert "Price not confirmed" in response.json()["detail"]
        assert not Stock.objects.filter(source="purchase_order").exists()
        po.refresh_from_db()
        assert po.status == "submitted"

    def test_a_price_tbc_job_line_also_blocks_fully_received_with_a_400(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        job: Job,
    ) -> None:
        po = make_purchase_order(status="submitted")
        make_po_line(po, quantity="2.00", unit_cost=None, price_tbc=True, job=job)
        etag = client.get(f"{PO_URL}{po.id}/").headers["ETag"]

        response = client.patch(
            f"{PO_URL}{po.id}/",
            data={"status": "fully_received"},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 400
        assert "Price not confirmed" in response.json()["detail"]

    def test_a_patched_line_still_receipts_after_a_price_tbc_toggle(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        """The regression the coupled unit_cost bug produced, end to end."""
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="4.00", unit_cost="25.00")
        etag = client.get(f"{PO_URL}{po.id}/").headers["ETag"]
        client.patch(
            f"{PO_URL}{po.id}/",
            data={"lines": [{"id": str(line.id), "price_tbc": False}]},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        _receipt(client, po, str(line.id), str(stock_holding_job.id), "4")

        stock = Stock.objects.get(source="purchase_order")
        assert stock.unit_cost == Decimal("25.00")

    def test_already_allocated_lines_are_not_duplicated(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="6.00", job=None)
        _receipt(client, po, str(line.id), str(stock_holding_job.id), "6")
        etag = client.get(f"{PO_URL}{po.id}/").headers["ETag"]

        client.patch(
            f"{PO_URL}{po.id}/",
            data={"status": "fully_received"},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert Stock.objects.filter(source="purchase_order").count() == 1


@pytest.mark.usefixtures("company_defaults")
def test_onward_issue_is_not_a_second_receipt_allocation(
    client: Client, stock_holding_job: Job, job: Job
) -> None:
    """Onward issues must neither hide their stock lot nor appear as additional PO receipts."""
    po = make_purchase_order(status="submitted")
    line = make_po_line(po, quantity="5")
    _receipt(client, po, str(line.id), str(stock_holding_job.id), "5")
    stock = Stock.objects.get(source_purchase_order_line=line)
    issued = client.post(
        f"/api/purchasing/stock/{stock.id}/consume/",
        {"job_id": str(job.id), "quantity": "2"},
        content_type="application/json",
    )
    assert issued.status_code == 200, issued.content
    allocations = client.get(f"{PO_URL}{po.id}/allocations/").json()["allocations"][str(line.id)]
    assert len(allocations) == 1
    assert allocations[0]["type"] == "stock"
    assert allocations[0]["allocation_id"] == str(stock.id)
    assert allocations[0]["quantity"] == 3
    cost = CostLine.objects.get(cost_set__job=job, kind="material")
    response = client.get(f"{PO_URL}{po.id}/allocations/job/{cost.id}/details/")
    assert response.status_code == 404


def test_purchase_order_quantities_and_prices_are_json_numbers(client: Client) -> None:
    """A browser must not receive decimal strings for quantities or confirmed prices (ADR 0046)."""
    po = make_purchase_order()
    make_po_line(po, quantity="2.25", received_quantity="1.25", unit_cost="12.34")
    line = client.get(f"{PO_URL}{po.id}/").json()["lines"][0]
    assert (line["quantity"], line["received_quantity"], line["unit_cost"]) == (2.25, 1.25, 12.34)


def test_full_receipt_after_a_partial_receipt_books_only_the_remainder(
    api: Client, stock_holding_job: Job, job: Job
) -> None:
    po = make_purchase_order(status="submitted")
    line = make_po_line(po, quantity="5", job=job)
    _receipt(api, po, str(line.id), str(stock_holding_job.id), "2")
    original = Stock.objects.get(source_purchase_order_line=line)
    response = api.patch(
        f"{PO_URL}{po.id}/",
        {"status": "fully_received"},
        content_type="application/json",
        headers={"If-Match": api.get(f"{PO_URL}{po.id}/").headers["ETag"]},
    )
    assert response.status_code == 200, response.content
    line.refresh_from_db()
    original.refresh_from_db()
    assert line.received_quantity == 5
    assert original.quantity == 2
    cost = CostLine.objects.get(stockmovement__stock__source_purchase_order_line=line)
    assert cost.quantity == 3
    assert cost.unit_cost == line.unit_cost


def test_local_order_amendment_cannot_erase_received_quantity(
    api: Client, stock_holding_job: Job
) -> None:
    po = make_purchase_order(status="submitted")
    line = make_po_line(po, quantity="5")
    _receipt(api, po, str(line.id), str(stock_holding_job.id), "2")
    response = api.patch(
        f"{PO_URL}{po.id}/",
        {"lines": [{"id": str(line.id), "quantity": "1", "unit_cost": "90"}]},
        content_type="application/json",
        headers={"If-Match": api.get(f"{PO_URL}{po.id}/").headers["ETag"]},
    )
    assert response.status_code == 400, response.content
    line.refresh_from_db()
    assert (line.quantity, line.unit_cost, line.received_quantity) == (
        Decimal("5"),
        Decimal("25"),
        Decimal("2"),
    )


def test_receipt_status_does_not_offset_one_lines_shortfall_against_another(
    api: Client, stock_holding_job: Job
) -> None:
    po = make_purchase_order(status="submitted")
    extra = make_po_line(po, quantity="1", description="Individual fitting")
    missing = make_po_line(po, quantity="100", description="Cable metres")
    _receipt(api, po, str(extra.id), str(stock_holding_job.id), "101")
    po.refresh_from_db()
    missing.refresh_from_db()
    assert po.status == "partially_received"
    assert missing.received_quantity == 0
