import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.workflow.models import AppError


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
def client(office_staff):
    api = APIClient()
    api.force_authenticate(user=office_staff)
    return api


def test_list_groups_returns_shape(client, db):
    AppError.objects.create(message="Dup", app="workflow", severity=40)
    AppError.objects.create(message="Dup", app="workflow", severity=40)

    resp = client.get("/api/app-errors/grouped/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    row = body["results"][0]
    assert row["message"] == "Dup"
    assert row["occurrence_count"] == 2
    assert "fingerprint" in row


def test_resolve_cascades(client, office_staff, db):
    AppError.objects.create(message="Cascade", app="workflow", severity=40)
    AppError.objects.create(message="Cascade", app="workflow", severity=40)

    resp = client.post(
        "/api/app-errors/grouped/mark_resolved/",
        data={"message": "Cascade"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2}
    assert AppError.objects.filter(resolved=True).count() == 2


def test_unresolve_cascades(client, office_staff, db):
    AppError.objects.create(message="Un", app="workflow", severity=40, resolved=True)
    AppError.objects.create(message="Un", app="workflow", severity=40, resolved=True)

    resp = client.post(
        "/api/app-errors/grouped/mark_unresolved/",
        data={"message": "Un"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2}


def test_xero_grouped_endpoint(client, db):
    from apps.workflow.models import XeroError

    XeroError.objects.create(
        message="Skip bill", entity="Bill", reference_id="b1", kind="Xero"
    )
    XeroError.objects.create(
        message="Skip bill", entity="Bill", reference_id="b1", kind="Xero"
    )

    resp = client.get("/api/xero-errors/grouped/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["occurrence_count"] == 2
