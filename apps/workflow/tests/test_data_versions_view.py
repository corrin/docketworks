from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.purchasing.models import Stock


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
def auth_client(office_staff):
    api = APIClient()
    api.force_authenticate(user=office_staff)
    return api


def _stock(**overrides):
    defaults = dict(
        description="Test material",
        quantity=Decimal("1.00"),
        unit_cost=Decimal("10.00"),
    )
    defaults.update(overrides)
    return Stock.objects.create(**defaults)


def test_get_returns_dict_with_stock_key(auth_client, db):
    resp = auth_client.get("/api/data-versions/")
    assert resp.status_code == 200
    body = resp.json()
    assert "stock" in body
    assert isinstance(body["stock"], str)
    assert body["stock"]


def test_response_has_no_store_cache_header(auth_client, db):
    resp = auth_client.get("/api/data-versions/")
    assert resp["Cache-Control"] == "no-store"


def test_unauthenticated_request_is_rejected(db):
    resp = APIClient().get("/api/data-versions/")
    assert resp.status_code in (401, 403)


def test_creating_stock_changes_version(auth_client, db):
    before = auth_client.get("/api/data-versions/").json()["stock"]
    _stock(description="New item")
    after = auth_client.get("/api/data-versions/").json()["stock"]
    assert before != after


def test_saving_stock_changes_version(auth_client, db):
    item = _stock(description="Initial")
    before = auth_client.get("/api/data-versions/").json()["stock"]
    item.unit_cost = Decimal("99.99")
    item.save()
    after = auth_client.get("/api/data-versions/").json()["stock"]
    assert before != after


def test_save_with_update_fields_still_bumps_version(auth_client, db):
    """The model's save() override merges 'updated_at' into update_fields,
    so a partial save like the Xero sync's `save(update_fields=['unit_cost'])`
    still triggers a version bump — that's the whole point of the field."""
    item = _stock(description="Partial save")
    before = auth_client.get("/api/data-versions/").json()["stock"]
    item.unit_cost = Decimal("196.04")
    item.save(update_fields=["unit_cost"])
    after = auth_client.get("/api/data-versions/").json()["stock"]
    assert before != after


def test_repeat_call_without_changes_returns_same_version(auth_client, db):
    _stock()
    first = auth_client.get("/api/data-versions/").json()["stock"]
    second = auth_client.get("/api/data-versions/").json()["stock"]
    assert first == second
