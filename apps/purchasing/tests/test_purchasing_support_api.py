"""API tests for the supporting purchasing surfaces.

Job pickers, supplier lookup, the PO PDF stream, supplier price status and the
product-parsing-mapping review endpoints.
"""

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.http import FileResponse
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company, SupplierSearchAlias
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder, Stock
from apps.purchasing.tests.conftest import make_po_line, make_purchase_order, make_stock
from apps.quoting.models import ProductParsingMapping, SupplierPriceList, SupplierProduct

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.purchasing.tests.urls"),
]


@pytest.mark.usefixtures("company_defaults")
class TestJobPickers:
    def test_all_jobs_flags_the_stock_holding_job(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        body = client.get("/api/purchasing/all-jobs/").json()

        assert body["success"] is True
        assert body["stock_holding_job_id"] == str(stock_holding_job.id)
        flags = {row["id"]: row["is_stock_holding"] for row in body["jobs"]}
        assert flags[str(stock_holding_job.id)] is True
        assert flags[str(job.id)] is False

    def test_all_jobs_excludes_archived_jobs(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        job: Job,
    ) -> None:
        Job.objects.filter(pk=job.pk).untracked_update(status="archived")

        ids = {row["id"] for row in client.get("/api/purchasing/all-jobs/").json()["jobs"]}

        assert str(job.id) not in ids

    def test_purchasing_jobs_lists_costable_jobs_with_their_actual_cost_set(
        self, client: Client, job: Job
    ) -> None:
        Job.objects.filter(pk=job.pk).untracked_update(status="in_progress")

        rows = client.get("/api/purchasing/jobs/").json()

        row = next(row for row in rows if row["id"] == str(job.id))
        assert row["cost_set_id"] == str(job.latest_actual.id)
        assert row["job_display_name"] == f"{job.job_number} - {job.name}"

    def test_purchasing_jobs_excludes_jobs_in_non_costable_states(
        self, client: Client, job: Job
    ) -> None:
        # Draft (the fixture's state), archived, rejected and completed jobs
        # cannot carry purchasing costs.
        assert client.get("/api/purchasing/jobs/").json() == []

        Job.objects.filter(pk=job.pk).untracked_update(status="archived")
        assert client.get("/api/purchasing/jobs/").json() == []


@pytest.mark.usefixtures("company_defaults")
class TestSupplierSearch:
    def test_an_empty_query_lists_suppliers_by_recent_purchases(
        self,
        client: Client,
        office_staff: Staff,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
    ) -> None:
        busy = make_company("Busy Steel")
        quiet = make_company("Quiet Metals")
        PurchaseOrder.objects.create(supplier=busy, order_date=timezone.localdate())

        body = client.get("/api/purchasing/suppliers/search/").json()

        names = [row["name"] for row in body["results"]]
        assert names.index(busy.name) < names.index(quiet.name)
        assert body["count"] >= 2

    def test_a_name_query_finds_the_supplier(self, client: Client) -> None:
        wanted = make_company("Steel & Tube")
        make_company("Completely Different Ltd")

        body = client.get("/api/purchasing/suppliers/search/?q=steel and tube").json()

        assert [row["name"] for row in body["results"]] == [wanted.name]

    def test_an_alias_matches_too(self, client: Client) -> None:
        supplier = make_company("Pacific Steel Limited")
        SupplierSearchAlias.objects.create(company=supplier, alias="PSL")

        body = client.get("/api/purchasing/suppliers/search/?q=PSL").json()

        assert [row["name"] for row in body["results"]] == [supplier.name]

    def test_archived_and_merged_companies_are_excluded(self, client: Client) -> None:
        survivor = make_company("Survivor Steel")
        make_company("Archived Steel", xero_archived=True)
        make_company("Merged Steel", merged_into=survivor)

        body = client.get("/api/purchasing/suppliers/search/?q=steel").json()

        assert [row["name"] for row in body["results"]] == [survivor.name]

    def test_recent_purchase_counts_ignore_deleted_and_stale_orders(self, client: Client) -> None:
        supplier = make_company("Counted Steel")
        PurchaseOrder.objects.create(supplier=supplier, order_date=timezone.localdate())
        PurchaseOrder.objects.create(
            supplier=supplier, order_date=timezone.localdate(), status="deleted"
        )
        PurchaseOrder.objects.create(
            supplier=supplier, order_date=timezone.localdate() - timedelta(days=800)
        )

        body = client.get("/api/purchasing/suppliers/search/?q=counted").json()

        assert body["results"][0]["recent_purchase_count"] == 1

    def test_pagination_reports_totals(self, client: Client) -> None:
        for index in range(3):
            make_company(f"Paged Steel {index}")

        body = client.get("/api/purchasing/suppliers/search/?q=paged&page=2&page_size=2").json()

        assert body["count"] == 3
        assert body["page"] == 2
        assert body["total_pages"] == 2
        assert len(body["results"]) == 1


class TestPurchaseOrderPdf:
    def test_streams_a_pdf_attachment(
        self, client: Client, supplier: Company, company_defaults: CompanyDefaults, job: Job
    ) -> None:
        company_defaults.logo_wide = "app_images/docketworks_logo_wide.png"
        company_defaults.save()
        po = make_purchase_order(supplier=supplier)
        make_po_line(po, description="50x50 SHS", item_code="SHS-50", job=job)

        response = client.get(f"/api/purchasing/purchase-orders/{po.id}/pdf/")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert f"Purchase_Order_{po.po_number}.pdf" in response["Content-Disposition"]
        pdf = b"".join(cast("Iterator[bytes]", cast("FileResponse", response).streaming_content))
        assert pdf.startswith(b"%PDF")

    @pytest.mark.usefixtures("company_defaults")
    def test_a_missing_logo_is_a_transparent_500(self, client: Client) -> None:
        # ADR 0038: the operator is told exactly what is not configured.
        po = make_purchase_order()

        response = client.get(f"/api/purchasing/purchase-orders/{po.id}/pdf/")

        assert response.status_code == 500
        assert "No wide logo uploaded" in response.json()["detail"]

    @pytest.mark.usefixtures("company_defaults")
    def test_an_unknown_purchase_order_is_404(self, client: Client) -> None:
        assert client.get(f"/api/purchasing/purchase-orders/{uuid4()}/pdf/").status_code == 404


@pytest.mark.usefixtures("company_defaults")
class TestSupplierPriceStatus:
    def test_reports_the_latest_upload_and_change_count_per_supplier(self, client: Client) -> None:
        supplier = make_company("Priced Steel")
        older = SupplierPriceList.objects.create(supplier=supplier, file_name="old.csv")
        newer = SupplierPriceList.objects.create(supplier=supplier, file_name="new.csv")
        SupplierProduct.objects.create(
            supplier=supplier,
            price_list=older,
            product_name="Dropped",
            item_no="A",
            variant_id="1",
            url="https://example.com/a",
        )
        SupplierProduct.objects.create(
            supplier=supplier,
            price_list=newer,
            product_name="Added",
            item_no="B",
            variant_id="1",
            url="https://example.com/b",
        )

        body = client.get("/api/purchasing/supplier-price-status/").json()

        assert body["total_count"] == 1
        item = body["items"][0]
        assert item["supplier_name"] == supplier.name
        assert item["file_name"] == "new.csv"
        assert item["total_products"] == 2
        # One key added, one removed between the two lists.
        assert item["changes_last_update"] == 2

    def test_suppliers_without_price_lists_are_omitted(self, client: Client) -> None:
        make_company("No Prices Ltd")
        assert client.get("/api/purchasing/supplier-price-status/").json() == {
            "items": [],
            "total_count": 0,
        }


@pytest.mark.usefixtures("company_defaults")
class TestProductMappings:
    def _mapping(
        self, *, input_hash: str, validated: bool, item_code: str | None
    ) -> ProductParsingMapping:
        return ProductParsingMapping.objects.create(
            input_hash=input_hash,
            input_data={"raw": input_hash},
            mapped_item_code=item_code,
            is_validated=validated,
            validated_at=timezone.now() if validated else None,
        )

    def test_list_puts_unvalidated_mappings_first_with_counts(self, client: Client) -> None:
        self._mapping(input_hash="validated", validated=True, item_code=None)
        self._mapping(input_hash="pending", validated=False, item_code=None)

        body = client.get("/api/purchasing/product-mappings/").json()

        assert body["total_count"] == 2
        assert body["validated_count"] == 1
        assert body["unvalidated_count"] == 1
        assert body["items"][0]["input_hash"] == "pending"

    def test_validating_marks_the_mapping_and_backflows_to_products(
        self, client: Client, office_staff: Staff
    ) -> None:
        supplier = make_company("Mapped Steel")
        price_list = SupplierPriceList.objects.create(supplier=supplier, file_name="p.csv")
        mapping = self._mapping(input_hash="hash-1", validated=False, item_code=None)
        product = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Raw name",
            item_no="X",
            variant_id="1",
            url="https://example.com/x",
            mapping_hash="hash-1",
        )

        response = client.post(
            f"/api/purchasing/product-mappings/{mapping.id}/validate/",
            data={"mapped_description": "50x50 SHS", "mapped_alloy": "350"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["updated_products_count"] == 1
        mapping.refresh_from_db()
        assert mapping.is_validated is True
        assert mapping.validated_by_id == office_staff.id
        assert mapping.mapped_description == "50x50 SHS"
        product.refresh_from_db()
        assert product.parsed_description == "50x50 SHS"
        assert product.parsed_alloy == "350"

    @pytest.mark.parametrize(
        "field",
        [
            "mapped_item_code",
            "mapped_description",
            "mapped_metal_type",
            "mapped_alloy",
            "mapped_specifics",
            "mapped_dimensions",
            "mapped_price_unit",
            "validation_notes",
        ],
    )
    def test_blank_nullable_text_is_a_validation_error(self, client: Client, field: str) -> None:
        """Unset is NULL (ADR 0040): "" is refused at the schema, same as PO lines."""
        mapping = self._mapping(input_hash="hash-blank", validated=False, item_code=None)

        response = client.post(
            f"/api/purchasing/product-mappings/{mapping.id}/validate/",
            data={field: ""},
            content_type="application/json",
        )

        assert response.status_code == 422, f"{field} blank should be a validation error"
        mapping.refresh_from_db()
        assert mapping.is_validated is False

    def test_an_item_code_absent_from_stock_is_cleared(self, client: Client) -> None:
        mapping = self._mapping(input_hash="hash-2", validated=False, item_code=None)

        client.post(
            f"/api/purchasing/product-mappings/{mapping.id}/validate/",
            data={"mapped_item_code": "NOT-IN-STOCK"},
            content_type="application/json",
        )

        mapping.refresh_from_db()
        assert mapping.item_code_is_in_xero is False
        assert mapping.mapped_item_code is None

    def test_an_item_code_present_in_stock_is_kept(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        make_stock(stock_holding_job, item_code="IN-STOCK", quantity="1.00")
        mapping = self._mapping(input_hash="hash-3", validated=False, item_code=None)

        client.post(
            f"/api/purchasing/product-mappings/{mapping.id}/validate/",
            data={"mapped_item_code": "IN-STOCK"},
            content_type="application/json",
        )

        mapping.refresh_from_db()
        assert mapping.item_code_is_in_xero is True
        assert mapping.mapped_item_code == "IN-STOCK"

    def test_an_unknown_mapping_is_404(self, client: Client) -> None:
        response = client.post(
            f"/api/purchasing/product-mappings/{uuid4()}/validate/",
            data={},
            content_type="application/json",
        )
        assert response.status_code == 404


@pytest.mark.usefixtures("company_defaults")
class TestShopJobStockAllocation:
    def test_stock_created_from_a_receipt_carries_the_company_markup(
        self, client: Client, stock_holding_job: Job, office_staff: Staff
    ) -> None:
        make_job(CompanyDefaults.get_solo().shop_company, office_staff, name="Shop side")
        po = make_purchase_order(status="submitted")
        line = make_po_line(po, quantity="1.00", unit_cost="10.00")
        etag = client.get(f"/api/purchasing/purchase-orders/{po.id}/").headers["ETag"]

        client.post(
            "/api/purchasing/delivery-receipts/",
            data={
                "purchase_order_id": str(po.id),
                "allocations": {
                    str(line.id): {
                        "total_received": "1",
                        "allocations": [{"job_id": str(stock_holding_job.id), "quantity": "1"}],
                    }
                },
            },
            content_type="application/json",
            headers={"If-Match": etag},
        )

        stock = Stock.objects.get(source="purchase_order")
        assert stock.unit_revenue == Decimal("12.00")
