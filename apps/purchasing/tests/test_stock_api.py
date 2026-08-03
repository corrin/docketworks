"""API tests for the Stock surface: CRUD, soft delete, consume, and search."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.test import Client

from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock
from apps.purchasing.tests.conftest import make_stock

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.purchasing.tests.urls"),
]

STOCK_URL = "/api/purchasing/stock/"


@pytest.mark.usefixtures("company_defaults")
class TestStockCrud:
    def test_list_returns_active_stock_newest_first(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        older = make_stock(stock_holding_job, description="Older")
        newer = make_stock(stock_holding_job, description="Newer")
        make_stock(stock_holding_job, description="Retired", is_active=False)

        rows = client.get(STOCK_URL).json()

        assert [row["description"] for row in rows] == [newer.description, older.description]

    def test_create_puts_the_row_on_the_stock_holding_job(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        response = client.post(
            STOCK_URL,
            data={
                "description": "6mm plate",
                "quantity": "3",
                "unit_cost": "80.00",
                "source": "manual",
                "location": "Rack 1",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        stock = Stock.objects.get(id=response.json()["id"])
        assert stock.job_id == stock_holding_job.id
        assert stock.location == "Rack 1"
        assert stock.is_active is True

    @pytest.mark.parametrize("field", ["item_code", "location", "metal_type", "alloy", "specifics"])
    def test_blank_nullable_text_on_create_is_a_validation_error(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
        field: str,
    ) -> None:
        """Unset is NULL (ADR 0040): "" is refused at the schema, same as PO lines."""
        response = client.post(
            STOCK_URL,
            data={
                "description": "Rod",
                "quantity": "1",
                "unit_cost": "5.00",
                "source": "manual",
                field: "",
            },
            content_type="application/json",
        )

        assert response.status_code == 422, f"{field} blank should be a validation error"
        assert Stock.objects.count() == 0

    @pytest.mark.parametrize("field", ["item_code", "location", "metal_type", "alloy", "specifics"])
    def test_blank_nullable_text_on_patch_is_a_validation_error(
        self, client: Client, stock_holding_job: Job, field: str
    ) -> None:
        stock = make_stock(stock_holding_job)
        setattr(stock, field, "keep-me")
        stock.save()

        response = client.patch(
            f"{STOCK_URL}{stock.id}/",
            data={field: ""},
            content_type="application/json",
        )

        assert response.status_code == 422, f"{field} blank should be a validation error"
        stock.refresh_from_db()
        assert getattr(stock, field) == "keep-me"

    @pytest.mark.parametrize("field", ["item_code", "location", "metal_type", "alloy", "specifics"])
    def test_explicit_null_clears_a_nullable_text_field(
        self, client: Client, stock_holding_job: Job, field: str
    ) -> None:
        stock = make_stock(stock_holding_job)
        setattr(stock, field, "something")
        stock.save()

        response = client.patch(
            f"{STOCK_URL}{stock.id}/",
            data={field: None},
            content_type="application/json",
        )

        assert response.status_code == 200
        stock.refresh_from_db()
        assert getattr(stock, field) is None

    def test_retrieve_returns_the_stock_row(self, client: Client, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job, description="Angle")

        body = client.get(f"{STOCK_URL}{stock.id}/").json()

        assert body["description"] == "Angle"
        assert body["job_id"] == str(stock_holding_job.id)
        assert body["times_used"] == 0

    def test_put_replaces_the_row(self, client: Client, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job, description="Old", quantity="1.00")

        client.put(
            f"{STOCK_URL}{stock.id}/",
            data={
                "description": "New",
                "quantity": "9",
                "unit_cost": "12.00",
                "source": "manual",
            },
            content_type="application/json",
        )

        stock.refresh_from_db()
        assert stock.description == "New"
        assert stock.quantity == Decimal("9.00")

    def test_patch_leaves_unsent_fields_alone(self, client: Client, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job, description="Keep", quantity="7.00")

        client.patch(
            f"{STOCK_URL}{stock.id}/",
            data={"description": "Renamed"},
            content_type="application/json",
        )

        stock.refresh_from_db()
        assert stock.description == "Renamed"
        assert stock.quantity == Decimal("7.00")

    def test_delete_is_a_soft_delete(self, client: Client, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job)

        response = client.delete(f"{STOCK_URL}{stock.id}/")

        assert response.status_code == 204
        stock.refresh_from_db()
        assert stock.is_active is False

    def test_an_inactive_row_is_not_reachable(self, client: Client, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job, is_active=False)
        assert client.get(f"{STOCK_URL}{stock.id}/").status_code == 404

    def test_negative_unit_cost_is_rejected_by_the_model(
        self,
        client: Client,
        stock_holding_job: Job,  # noqa: ARG002 -- present so Stock.get_stock_holding_job() resolves
    ) -> None:
        response = client.post(
            STOCK_URL,
            data={
                "description": "Broken",
                "quantity": "1",
                "unit_cost": "-1.00",
                "source": "manual",
            },
            content_type="application/json",
        )

        assert response.status_code == 500
        assert "Unit cost cannot be negative" in response.json()["detail"]


@pytest.mark.usefixtures("company_defaults")
class TestConsumeStock:
    def test_consuming_draws_the_row_down_and_books_a_material_line(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        stock = make_stock(
            stock_holding_job, description="Bar", quantity="10.00", unit_cost="20.00"
        )

        response = client.post(
            f"{STOCK_URL}{stock.id}/consume/",
            data={"job_id": str(job.id), "quantity": "4"},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert Decimal(body["remaining_quantity"]) == Decimal("6.00")
        stock.refresh_from_db()
        assert stock.quantity == Decimal("6.00")

        cost_line = CostLine.objects.get(id=body["line"]["id"])
        assert cost_line.kind == "material"
        assert cost_line.desc == "Bar"
        assert cost_line.quantity == Decimal("4.000")
        assert cost_line.unit_cost == Decimal("20.00")
        # 20% company markup by default.
        assert cost_line.unit_rev == Decimal("24.00")
        assert cost_line.ext_refs["stock_id"] == str(stock.id)
        assert cost_line.cost_set.job_id == job.id

    def test_explicit_rates_override_the_defaults(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        stock = make_stock(stock_holding_job, quantity="10.00", unit_cost="20.00")

        body = client.post(
            f"{STOCK_URL}{stock.id}/consume/",
            data={
                "job_id": str(job.id),
                "quantity": "1",
                "unit_cost": "11.00",
                "unit_rev": "99.00",
            },
            content_type="application/json",
        ).json()

        cost_line = CostLine.objects.get(id=body["line"]["id"])
        assert cost_line.unit_cost == Decimal("11.00")
        assert cost_line.unit_rev == Decimal("99.00")

    def test_consuming_more_than_held_is_allowed_and_goes_negative(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        # Backorders and emergency usage are real; v1 logged and allowed it.
        stock = make_stock(stock_holding_job, quantity="2.00")

        response = client.post(
            f"{STOCK_URL}{stock.id}/consume/",
            data={"job_id": str(job.id), "quantity": "5"},
            content_type="application/json",
        )

        assert response.status_code == 200
        stock.refresh_from_db()
        assert stock.quantity == Decimal("-3.00")

    def test_zero_quantity_is_rejected(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        stock = make_stock(stock_holding_job)

        response = client.post(
            f"{STOCK_URL}{stock.id}/consume/",
            data={"job_id": str(job.id), "quantity": "0"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "must be positive" in response.json()["detail"]

    def test_an_unknown_job_is_404(self, client: Client, stock_holding_job: Job) -> None:
        stock = make_stock(stock_holding_job)

        response = client.post(
            f"{STOCK_URL}{stock.id}/consume/",
            data={"job_id": str(uuid4()), "quantity": "1"},
            content_type="application/json",
        )

        assert response.status_code == 404


@pytest.mark.usefixtures("company_defaults")
class TestStockSearch:
    def test_short_queries_list_everything(self, client: Client, stock_holding_job: Job) -> None:
        make_stock(stock_holding_job, description="Alpha")
        make_stock(stock_holding_job, description="Beta")

        body = client.get(f"{STOCK_URL}search/?q=ab").json()

        assert body["count"] == 2
        assert body["page"] == 1
        assert body["total_pages"] == 1

    def test_inactive_rows_are_excluded(self, client: Client, stock_holding_job: Job) -> None:
        make_stock(stock_holding_job, description="Live")
        make_stock(stock_holding_job, description="Retired", is_active=False)

        assert client.get(f"{STOCK_URL}search/").json()["count"] == 1

    def test_pagination_slices_and_reports_totals(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        for index in range(5):
            make_stock(stock_holding_job, description=f"Item {index}")

        body = client.get(f"{STOCK_URL}search/?page=2&page_size=2").json()

        assert body["count"] == 5
        assert body["page"] == 2
        assert body["page_size"] == 2
        assert body["total_pages"] == 3
        assert len(body["results"]) == 2

    def test_sorting_honours_the_allowed_fields(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        make_stock(stock_holding_job, description="B item", quantity="1.00")
        make_stock(stock_holding_job, description="A item", quantity="2.00")

        ascending = client.get(f"{STOCK_URL}search/?sort_by=description&sort_dir=asc").json()
        descending = client.get(f"{STOCK_URL}search/?sort_by=description&sort_dir=desc").json()

        assert [row["description"] for row in ascending["results"]] == ["A item", "B item"]
        assert [row["description"] for row in descending["results"]] == ["B item", "A item"]

    def test_merchant_shorthand_finds_the_matching_row(
        self, client: Client, stock_holding_job: Job
    ) -> None:
        wanted = make_stock(
            stock_holding_job,
            description="50x50 SHS galvanised",
            metal_type="mild_steel",
            item_code="SHS-50",
        )
        make_stock(stock_holding_job, description="6mm stainless sheet", item_code="SS-6")

        body = client.get(f"{STOCK_URL}search/?q=50x50 SHS galv").json()

        assert next(row["id"] for row in body["results"]) == str(wanted.id)

    def test_usage_counts_ride_along_with_search_results(
        self, client: Client, stock_holding_job: Job, job: Job
    ) -> None:
        make_stock(stock_holding_job, description="Counted", item_code="CNT-1")
        CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="material",
            desc="Used CNT-1",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("1.00"),
            unit_rev=Decimal("1.00"),
            accounting_date=job.created_at.date(),
            meta={"item_code": "CNT-1"},
        )

        body = client.get(f"{STOCK_URL}search/").json()

        assert body["results"][0]["times_used"] == 1
