"""Postgres FTS regression coverage for stock search (Trello #150).

Same bug class as the client search: `description.includes(query)` (and the
backend's `description__icontains`) matched the query as a contiguous
substring, so `"5mm stainless"` could not find `"stainless 5mm sheet"`.
These tests pin token-order independence, phrase ranking, the structured
field branch (alloy / metal_type / specifics), and the `is_active=True`
filter.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.purchasing.models import Stock
from apps.purchasing.services.stock_search_service import list_stock, search_stock


def _stock(**overrides):
    defaults = dict(
        description="Generic material",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
        is_active=True,
    )
    defaults.update(overrides)
    return Stock.objects.create(**defaults)


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


def test_search_stock_short_query_is_rejected(db):
    assert search_stock("ab") == []
    assert search_stock("") == []


def test_search_stock_top_n_orders_by_rank(stainless_sheet, stainless_5mm_other_finish):
    """search_stock() returns rank-ordered results capped at limit."""
    results = search_stock("stainless", limit=10)
    assert len(results) == 2
    descriptions = {r["description"] for r in results}
    assert descriptions == {
        "Stainless 5mm sheet 1200x2400",
        "5mm stainless dimpled finish",
    }


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


def test_view_returns_search_results_via_http(auth_api, db):
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

    resp = auth_api.get("/api/purchasing/stock/search/", {"q": "5mm"})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    descriptions = [r["description"] for r in body["results"]]
    assert "Stainless 5mm sheet" in descriptions
    assert "Aluminium bar" not in descriptions
    assert body["count"] >= 1
    assert body["page"] == 1


def test_view_unauthenticated_is_rejected(db):
    resp = APIClient().get("/api/purchasing/stock/search/", {"q": "anything"})
    assert resp.status_code in (401, 403)
