import hashlib

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.job.models.job_delta_rejection import JobDeltaRejection


def _fingerprint(reason: str) -> str:
    return hashlib.sha256(reason.encode("utf-8")).hexdigest()


@pytest.fixture
def office_staff(db):
    return Staff.objects.create(
        email="jd_office@example.test",
        first_name="O",
        last_name="S",
        password_needs_reset=False,
        is_office_staff=True,
    )


@pytest.fixture
def client(office_staff):
    api = APIClient()
    api.force_authenticate(user=office_staff)
    return api


def test_grouped_list_returns_shape(client, db):
    JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    JobDeltaRejection.objects.create(reason="stale_etag", envelope={})

    resp = client.get("/api/job/jobs/delta-rejections/grouped/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["reason"] == "stale_etag"
    assert body["results"][0]["occurrence_count"] == 2


def test_resolve_cascades(client, office_staff, db):
    JobDeltaRejection.objects.create(reason="conflict", envelope={})
    JobDeltaRejection.objects.create(reason="conflict", envelope={})

    resp = client.post(
        "/api/job/jobs/delta-rejections/grouped/mark_resolved/",
        data={"fingerprint": _fingerprint("conflict")},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2}
    assert JobDeltaRejection.objects.filter(resolved=True).count() == 2


def test_unresolve_cascades(client, office_staff, db):
    for _ in range(2):
        JobDeltaRejection.objects.create(reason="conflict", envelope={}, resolved=True)

    resp = client.post(
        "/api/job/jobs/delta-rejections/grouped/mark_unresolved/",
        data={"fingerprint": _fingerprint("conflict")},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2}
