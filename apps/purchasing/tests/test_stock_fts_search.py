"""Postgres FTS regression coverage for stock search (Trello #150).

Same bug class as the company search: `description.includes(query)` (and the
backend's `description__icontains`) matched the query as a contiguous
substring, so `"5mm stainless"` could not find `"stainless 5mm sheet"`.
These tests pin token-order independence, phrase ranking, the structured
field branch (alloy / metal_type / specifics), and the `is_active=True`
filter.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock
from apps.purchasing.services.stock_search_service import (
    MAX_SEARCH_QUERY_LENGTH,
    list_stock,
    search_stock,
)
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults, SearchTelemetryEvent


def _stock(**overrides):
    defaults = dict(
        description="Generic material",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
        is_active=True,
    )
    defaults.update(overrides)
    return Stock.objects.create(**defaults)


def _top_descriptions(query: str, *, page_size: int = 10, top_n: int = 3) -> list[str]:
    result = list_stock(query=query, page=1, page_size=page_size)
    return [r["description"] for r in result["results"]][:top_n]


@pytest.fixture
def hynds_pipe(db):
    return _stock(description="Hynds Pipe Systems steel section")


@pytest.fixture
def stainless_sheet(db):
    return _stock(description="Stainless 5mm sheet 1200x2400", alloy="304")


@pytest.fixture
def stainless_5mm_other_finish(db):
    return _stock(description="5mm stainless dimpled finish", alloy="316")


def test_multi_token_query_in_any_order(stainless_sheet, stainless_5mm_other_finish):
    """`5mm stainless` matches rows where the tokens appear in either order."""
    result = list_stock(query="5mm stainless", page=1, page_size=10)
    descriptions = [r["description"] for r in result["results"]]
    assert "Stainless 5mm sheet 1200x2400" in descriptions
    assert "5mm stainless dimpled finish" in descriptions


def test_quoted_phrase_outranks_scattered_tokens(
    stainless_sheet, stainless_5mm_other_finish
):
    """Quoted `"5mm stainless"` ranks the contiguous-phrase row first."""
    result = list_stock(query='"5mm stainless"', page=1, page_size=10)
    descriptions = [r["description"] for r in result["results"]]
    assert descriptions[0] == "5mm stainless dimpled finish"


def test_search_matches_alloy_field(db):
    """Querying `304` should match a row whose alloy is 304 even if the
    description does not mention it. Justifies including the vetted
    structured fields in the search vector."""
    _stock(description="Sheet metal", alloy="304", metal_type="stainless steel")
    _stock(description="Other sheet", alloy="6061", metal_type="aluminium")

    result = list_stock(query="304", page=1, page_size=10)
    descriptions = [r["description"] for r in result["results"]]
    assert "Sheet metal" in descriptions
    assert "Other sheet" not in descriptions


def test_numeric_query_matches_embedded_alloy_code_in_description(db):
    """`5005` must find legacy rows that only contain `5005H32` in description."""
    legacy = _stock(
        description="2.0X1200X3000 5005H32 AL SHTPE",
        item_code="0025084",
        alloy=None,
    )
    _stock(description="2.0X1200X3000 5052H32 AL SHTPE", item_code="0025085")

    result = list_stock(query="5005", page=1, page_size=10)
    descriptions = [r["description"] for r in result["results"]]

    assert legacy.description in descriptions
    assert "2.0X1200X3000 5052H32 AL SHTPE" not in descriptions


def test_numeric_query_boosts_alloy_and_item_code_matches(db):
    enriched = _stock(
        description="1.6X1200X2400 5005H32 AL SHT",
        item_code="SHT-1.6-AL5005H32-1200x2400",
        alloy="5005",
    )
    legacy = _stock(
        description="2.0X1200X3000 5005H32 AL SHTPE",
        item_code="0025084",
        alloy=None,
    )

    assert _top_descriptions("5005", top_n=2) == [
        enriched.description,
        legacy.description,
    ]


def test_search_matches_specifics_field(db):
    """Specifics field participates in the search vector."""
    _stock(
        description="Socket screw",
        specifics="m8 countersunk socket screw",
        alloy="",
    )

    result = list_stock(query="countersunk", page=1, page_size=10)
    assert len(result["results"]) == 1
    assert result["results"][0]["description"] == "Socket screw"


def test_inactive_stock_is_excluded(db):
    _stock(description="Active widget", is_active=True)
    _stock(description="Retired widget", is_active=False)

    result = list_stock(query="widget", page=1, page_size=10)
    descriptions = [r["description"] for r in result["results"]]
    assert "Active widget" in descriptions
    assert "Retired widget" not in descriptions


def test_no_match_returns_empty(db):
    """Regression: see the matching test in test_client_fts_search.py."""
    _stock(description="Steel sheet")
    result = list_stock(query="zzzqqxnonsense", page=1, page_size=10)
    assert result["results"] == []
    assert result["count"] == 0


def test_empty_query_lists_all_active(db):
    _stock(description="Item A", is_active=True)
    _stock(description="Item B", is_active=True)
    _stock(description="Item C", is_active=False)

    result = list_stock(query=None, page=1, page_size=10)
    descriptions = {r["description"] for r in result["results"]}
    assert descriptions == {"Item A", "Item B"}


def test_empty_query_paginates_cleanly(db):
    _stock(description="Item A", is_active=True)
    _stock(description="Item B", is_active=True)
    _stock(description="Item C", is_active=True)

    result = list_stock(query=None, page=2, page_size=1, sort_by="description")

    assert result["count"] == 3
    assert result["page"] == 2
    assert result["page_size"] == 1
    assert result["total_pages"] == 3
    assert len(result["results"]) == 1


def test_search_stock_short_query_is_rejected(db):
    assert search_stock("ab") == []
    assert search_stock("") == []


def test_search_stock_rejects_overly_long_query(db):
    with pytest.raises(ValueError, match="Search query too long"):
        search_stock("x" * (MAX_SEARCH_QUERY_LENGTH + 1))


def test_list_stock_rejects_overly_long_query(db):
    with pytest.raises(ValueError, match="Search query too long"):
        list_stock(query="x" * (MAX_SEARCH_QUERY_LENGTH + 1), page=1, page_size=10)


def test_search_stock_top_n_orders_by_rank(stainless_sheet, stainless_5mm_other_finish):
    """search_stock() returns rank-ordered results capped at limit."""
    results = search_stock("stainless", limit=10)
    assert len(results) == 2
    descriptions = {r["description"] for r in results}
    assert descriptions == {
        "Stainless 5mm sheet 1200x2400",
        "5mm stainless dimpled finish",
    }


def test_dimension_query_matches_compact_sheet_notation(db):
    """Users type `2400x1200 3mm`; stock descriptions often store
    `3.0X1200X2400 ...` without spaces and in the opposite dimension order.
    Search should still find the intended sheet row."""
    target = _stock(description="3.0X1200X2400 5052H32 AL SHT")
    _stock(description="2.0X1200X2400 5052H32 AL SHT")
    _stock(description="3mm 900X1800 mild steel sheet")

    assert target.description in _top_descriptions("2400x1200 3mm")


def test_dimension_query_treats_sheet_orientation_as_interchangeable(db):
    """`1200x2400` and `2400x1200` should describe the same sheet size."""
    target = _stock(description="3mm Cold Rolled Sheet 1200X2400")

    assert target.description in _top_descriptions("1200x2400 3mm")
    assert target.description in _top_descriptions("2400x1200 3mm")


def test_3mm_query_accepts_near_thickness_but_not_30mm(db):
    """`3mm` should treat `2.9mm` as close, but not rank `30mm` as a good hit."""
    exact = _stock(description="3.0mm stainless sheet")
    near = _stock(description="2.9mm stainless sheet")
    far = _stock(description="30mm stainless plate")

    descriptions = _top_descriptions("3mm", top_n=2)

    assert exact.description in descriptions
    assert near.description in descriptions
    assert far.description not in descriptions


@pytest.mark.parametrize("query", ["16 316", "316 round", "16 round"])
def test_round_bar_queries_surface_expected_material(db, query):
    target = _stock(description="16.0mm Dia Round Bar T316IM CDP h9 A276")
    _stock(description="16.0mm Dia Round Bar T304 CDP h9 A276")
    _stock(description="20.0mm Dia Round Bar T316IM CDP h9 A276")

    assert target.description in _top_descriptions(query)


def test_round_bar_8_prefers_metric_round_bar_over_fractional_or_fastener_noise(db):
    target = _stock(description="8.0mm Dia Round Bar T304IM CDP h9 A276")
    _stock(description='5/8" Dia Round Bar T316IM CDP h9 A276')
    _stock(description="50mm x 8mm Flat Bar G300 AS/NZS 3679.1 6MTRS")
    _stock(description="M8 X 22 X 2.5 GALV ROUND WASHER")

    assert _top_descriptions("Round Bar 8", top_n=1) == [target.description]


def test_flat_bar_8_prefers_flat_bar_over_round_bar(db):
    target = _stock(description="50mm x 8mm Flat Bar G300 AS/NZS 3679.1 6MTRS")
    _stock(description="8.0mm Dia Round Bar T304IM CDP h9 A276")
    _stock(description="M8 X 22 X 2.5 GALV ROUND WASHER")

    assert _top_descriptions("Flat Bar 8", top_n=1) == [target.description]


def test_m8_washer_prefers_fastener_form_over_bar_stock(db):
    target = _stock(description="M8 X 22 X 2.5 GALV ROUND WASHER")
    _stock(description="8.0mm Dia Round Bar T304IM CDP h9 A276")
    _stock(description="50mm x 8mm Flat Bar G300 AS/NZS 3679.1 6MTRS")

    assert _top_descriptions("M8 washer", top_n=1) == [target.description]


@pytest.mark.parametrize("query", ["0.95 galvanised", "0.95 sheet", "galv 0.95"])
def test_galvanised_sheet_queries_surface_expected_material(db, query):
    target = _stock(description="0.95mm Galvanised Z275 Regular Spangle Sheet G250")
    _stock(description="1.55mm Galvanised Z275 Regular Spangle Sheet G250")

    assert target.description in _top_descriptions(query)


class TestStockSearchHistoricalRanking(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client_obj = Company.objects.create(
            name="Stock Search Company",
            xero_last_modified=timezone.now(),
        )

    def _create_job(self, name: str) -> Job:
        job = Job(company=self.client_obj, name=name)
        job.save(staff=self.test_staff)
        return job

    def _record_material_usage(
        self, *, item_code: str, description: str, times: int
    ) -> None:
        job = self._create_job(f"Usage Job {item_code}")
        for _ in range(times):
            CostLine.objects.create(
                cost_set=job.latest_actual,
                kind="material",
                desc=description,
                quantity=Decimal("1.000"),
                unit_cost=Decimal("1.00"),
                unit_rev=Decimal("1.00"),
                accounting_date=date.today(),
                meta={"item_code": item_code},
            )

    def test_unspecified_alloy_prefers_more_frequently_used_variant(self):
        preferred = _stock(
            item_code="SS-304-1.5-1219X2438",
            description="1.5X1219X2438 3042B SS SHT FIBRE PE",
        )
        _stock(
            item_code="SS-316-1.5-1219X2438",
            description="1.5X1219X2438 3162B SS SHT FIBRE PE",
        )

        self._record_material_usage(
            item_code="SS-304-1.5-1219X2438",
            description=preferred.description,
            times=5,
        )
        self._record_material_usage(
            item_code="SS-316-1.5-1219X2438",
            description="1.5X1219X2438 3162B SS SHT FIBRE PE",
            times=2,
        )

        assert preferred.description in _top_descriptions("1.5 stainless")

    def test_explicit_alloy_overrides_historical_popularity(self):
        _stock(
            item_code="SS-304-1.5-1219X2438",
            description="1.5X1219X2438 3042B SS SHT FIBRE PE",
        )
        target = _stock(
            item_code="SS-316-1.5-1219X2438",
            description="1.5X1219X2438 3162B SS SHT FIBRE PE",
        )

        self._record_material_usage(
            item_code="SS-304-1.5-1219X2438",
            description="1.5X1219X2438 3042B SS SHT FIBRE PE",
            times=5,
        )
        self._record_material_usage(
            item_code="SS-316-1.5-1219X2438",
            description=target.description,
            times=2,
        )

        assert target.description in _top_descriptions("1.5 316")


@pytest.fixture
def office_staff(db):
    staff = Staff.objects.create(
        email="office@example.test",
        first_name="O",
        last_name="S",
        password_needs_reset=False,
        is_office_staff=True,
    )
    staff.set_password("pw")
    staff.save()
    return staff


@pytest.fixture
def auth_api(office_staff):
    api = APIClient()
    api.force_authenticate(user=office_staff)
    return api


def test_view_returns_search_results_via_http(auth_api, office_staff, db):
    """Regression: end-to-end through StockSearchRestView.

    The original bug was that the view re-validated the response payload via
    `StockSearchResponseSerializer(data=...).is_valid()`, which re-ran the
    nested ModelSerializer's unique-validator on `item_code` and rejected
    every row (because the rows it was supposedly creating already exist in
    the DB — they are the DB rows). The user observed `"5mm"` returning no
    results because the view 500-ed silently and the frontend treated the
    error as an empty result. This test exercises the full HTTP path so any
    re-introduction of the validate-then-respond pattern fails here.
    """
    _stock(description="Stainless 5mm sheet", item_code="STK-001")
    _stock(description="Aluminium bar", item_code="STK-002")
    company = Company.objects.create(
        name="Stock Search View Company",
        xero_last_modified=timezone.now(),
    )
    shop_company = Company.objects.create(
        name="Stock Search Shop Company",
        xero_last_modified=timezone.now(),
    )
    CompanyDefaults.objects.create(company_name="Test Co", shop_company=shop_company)
    job = Job(company=company, name="Stock Search View Job")
    job.save(staff=office_staff)
    CostLine.objects.create(
        cost_set=job.latest_actual,
        kind="material",
        desc="Stainless 5mm sheet",
        quantity=Decimal("1.000"),
        unit_cost=Decimal("1.00"),
        unit_rev=Decimal("1.00"),
        accounting_date=date.today(),
        meta={"item_code": "STK-001"},
    )

    resp = auth_api.get("/api/purchasing/stock/search/", {"q": "5mm"})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    descriptions = [r["description"] for r in body["results"]]
    assert "Stainless 5mm sheet" in descriptions
    assert "Aluminium bar" not in descriptions
    result_by_description = {row["description"]: row for row in body["results"]}
    assert result_by_description["Stainless 5mm sheet"]["times_used"] == 1
    assert body["count"] >= 1
    assert body["page"] == 1
    event = SearchTelemetryEvent.objects.get(
        event_type=SearchTelemetryEvent.EventType.SEARCH,
        domain=SearchTelemetryEvent.Domain.STOCK,
    )
    assert event.query == "5mm"
    assert event.result_count == body["count"]
    assert event.returned_result_ids
    assert event.metadata["results"][0]["description"] == "Stainless 5mm sheet"


def test_stock_list_view_includes_default_times_used(auth_api, db):
    _stock(description="Plain stock row", item_code="STK-LIST-001")

    resp = auth_api.get("/api/purchasing/stock/")

    assert resp.status_code == 200, resp.content
    body = resp.json()
    result_by_description = {row["description"]: row for row in body}
    assert result_by_description["Plain stock row"]["times_used"] == 0


def test_view_unauthenticated_is_rejected(db):
    resp = APIClient().get("/api/purchasing/stock/search/", {"q": "anything"})
    assert resp.status_code in (401, 403)


def test_view_rejects_overly_long_query(auth_api, db):
    resp = auth_api.get(
        "/api/purchasing/stock/search/",
        {"q": "x" * (MAX_SEARCH_QUERY_LENGTH + 1)},
    )

    assert resp.status_code == 400, resp.content
    assert resp.json() == {
        "error": "Invalid search query",
        "details": "Search query too long.",
    }


def test_view_clamps_page_size(auth_api, db):
    for index in range(120):
        _stock(description=f"Stock Item {index:03d}", item_code=f"STK-{index:03d}")

    resp = auth_api.get("/api/purchasing/stock/search/", {"page_size": 9999})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["page_size"] == 100
    assert body["count"] == 120
    assert len(body["results"]) == 100
