"""Supplier lookup search coverage for purchase orders (Trello #323)."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.client.models import Client, SupplierSearchAlias
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services.supplier_search_service import (
    _name_match_score,
    list_suppliers,
    normalize_supplier_phrase,
)


def _make_client(name: str, **overrides):
    defaults = {
        "name": name,
        "xero_last_modified": timezone.now(),
    }
    defaults.update(overrides)
    return Client.objects.create(**defaults)


def _make_po(supplier: Client, *, days_ago: int = 0, status: str = "draft"):
    sequence = PurchaseOrder.objects.count() + 1
    return PurchaseOrder.objects.create(
        supplier=supplier,
        po_number=f"PO-T323-{sequence}",
        order_date=timezone.localdate() - timedelta(days=days_ago),
        status=status,
    )


def _names(query: str) -> list[str]:
    result = list_suppliers(query=query, page=1, page_size=20)
    return [item["name"] for item in result["results"]]


def _supplier_name_score(name: str, query: str) -> float:
    return _name_match_score(
        [normalize_supplier_phrase(name)],
        normalize_supplier_phrase(query),
    )


@pytest.fixture
def auth_api(db):
    staff = Staff.objects.create(
        email="supplier-search@example.test",
        first_name="Supplier",
        last_name="Search",
        password_needs_reset=False,
        is_office_staff=True,
    )
    api = APIClient()
    api.force_authenticate(user=staff)
    return api


@pytest.mark.django_db
def test_s_and_t_matches_s_t_supplier_name():
    _make_client("S&T Stainless Limited")

    assert _names("S&T")[0] == "S&T Stainless Limited"


def test_s_and_t_scores_substring_match_above_reversed_initials():
    assert _supplier_name_score(
        "S&T Stainless Limited",
        "S&T",
    ) > _supplier_name_score(
        "T&S Stainless Limited",
        "S&T",
    )


@pytest.mark.django_db
def test_s_and_t_prefers_s_t_supplier_after_broad_single_letter_matches():
    for index in range(550):
        _make_client(f"Stainless Test Distractor {index:03d}")

    supplier = _make_client("S&T Stainless Limited - acct 2003173")
    for _ in range(112):
        _make_po(supplier)

    result = list_suppliers(query="S&T", page=1, page_size=50)

    assert result["results"][0]["name"] == "S&T Stainless Limited - acct 2003173"
    assert result["results"][0]["recent_purchase_count"] == 112
    assert all(
        not item["name"].startswith("Stainless Test Distractor")
        for item in result["results"]
    )


@pytest.mark.django_db
def test_s_and_t_ranks_s_t_before_t_s():
    _make_client("T&S Stainless Limited")
    _make_client("S&T Stainless Limited")

    assert _names("S&T")[:2] == [
        "S&T Stainless Limited",
        "T&S Stainless Limited",
    ]


@pytest.mark.django_db
def test_supplier_alias_matches_attached_client():
    supplier = _make_client("S&T Stainless Limited")
    SupplierSearchAlias.objects.create(client=supplier, alias="Steel and Tube")

    assert _names("Steel and Tube")[0] == "S&T Stainless Limited"


@pytest.mark.django_db
def test_allow_jobs_false_does_not_exclude_supplier():
    _make_client("S&T Stainless Limited", allow_jobs=False)

    assert _names("S&T")[0] == "S&T Stainless Limited"


@pytest.mark.django_db
def test_is_supplier_false_can_outrank_is_supplier_true_with_purchase_history():
    frequent = _make_client("S&T Stainless Limited", is_supplier=False)
    _make_client("S&T Stainless Alternate", is_supplier=True)
    _make_po(frequent)
    _make_po(frequent)

    assert _names("S&T Stainless")[0] == "S&T Stainless Limited"


@pytest.mark.django_db
def test_archived_and_merged_clients_are_excluded():
    active = _make_client("S&T Stainless Limited")
    _make_client("S&T Archived Limited", xero_archived=True)
    _make_client("S&T Merged Limited", merged_into=active)

    assert _names("S&T") == ["S&T Stainless Limited"]


@pytest.mark.django_db
def test_recent_purchase_history_boosts_but_old_history_does_not():
    recent = _make_client("Steel Supplier Recent")
    old = _make_client("Steel Supplier Old")
    _make_po(recent, days_ago=30)
    _make_po(recent, days_ago=60)
    _make_po(old, days_ago=800)
    _make_po(old, days_ago=900)
    _make_po(old, days_ago=1000)

    assert _names("Steel Supplier")[:2] == [
        "Steel Supplier Recent",
        "Steel Supplier Old",
    ]


@pytest.mark.django_db
def test_deleted_purchase_orders_do_not_boost_supplier():
    active_po_supplier = _make_client("Steel Supplier Active")
    deleted_po_supplier = _make_client("Steel Supplier Deleted")
    _make_po(active_po_supplier)
    _make_po(deleted_po_supplier)
    _make_po(deleted_po_supplier, status="deleted")
    _make_po(deleted_po_supplier, status="deleted")

    assert _names("Steel Supplier")[0] == "Steel Supplier Active"


@pytest.mark.django_db
def test_stop_word_only_query_falls_back_to_literal_name_match():
    _make_client("The Tool Shed")
    _make_client("The Metal Company")

    assert _names("The") == ["The Metal Company", "The Tool Shed"]


@pytest.mark.django_db
def test_supplier_alias_api_lists_creates_and_deactivates_alias(auth_api):
    client = _make_client("S&T Stainless Limited")

    create_resp = auth_api.post(
        f"/api/clients/{client.id}/supplier-aliases/",
        {"alias": "Steel and Tube"},
        format="json",
    )
    assert create_resp.status_code == 201, create_resp.content
    alias_id = create_resp.json()["id"]

    list_resp = auth_api.get(f"/api/clients/{client.id}/supplier-aliases/")
    assert list_resp.status_code == 200, list_resp.content
    assert [row["alias"] for row in list_resp.json()] == ["Steel and Tube"]

    delete_resp = auth_api.delete(f"/api/clients/supplier-aliases/{alias_id}/")
    assert delete_resp.status_code == 204, delete_resp.content

    list_resp = auth_api.get(f"/api/clients/{client.id}/supplier-aliases/")
    assert list_resp.status_code == 200, list_resp.content
    assert list_resp.json() == []


@pytest.mark.django_db
def test_supplier_search_view_returns_alias_match(auth_api):
    supplier = _make_client("S&T Stainless Limited")
    SupplierSearchAlias.objects.create(client=supplier, alias="Steel and Tube")

    resp = auth_api.get("/api/purchasing/suppliers/search/", {"q": "Steel and Tube"})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["results"][0]["name"] == "S&T Stainless Limited"
