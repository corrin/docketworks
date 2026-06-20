"""View-level filter parity for the admin error-triage tool.

The Xero individual list and the Job individual delta-rejection list gained the
same resolved/app filters the System tab already had. These guard that the query
params actually narrow the results.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.job.models.job_delta_rejection import JobDeltaRejection
from apps.workflow.models import XeroError


@pytest.fixture
def office_staff(db: None) -> Staff:
    return Staff.objects.create(
        email="errfilter_office@example.test",
        first_name="O",
        last_name="S",
        password_needs_reset=False,
        is_office_staff=True,
    )


@pytest.fixture
def client(office_staff: Staff) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=office_staff)
    return api


def test_job_individual_list_filters_by_resolved(
    client: APIClient, office_staff: Staff, db: None
) -> None:
    open_rej = JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
    done_rej = JobDeltaRejection.objects.create(reason="conflict", envelope={})
    done_rej.mark_resolved(office_staff)

    url = "/api/job/jobs/delta-rejections/"

    all_resp = client.get(url)
    assert all_resp.status_code == 200
    assert {row["id"] for row in all_resp.json()["results"]} == {
        str(open_rej.id),
        str(done_rej.id),
    }

    unresolved = client.get(url, {"resolved": "false"})
    assert unresolved.status_code == 200
    assert [row["id"] for row in unresolved.json()["results"]] == [str(open_rej.id)]

    resolved = client.get(url, {"resolved": "true"})
    assert resolved.status_code == 200
    assert [row["id"] for row in resolved.json()["results"]] == [str(done_rej.id)]


def test_job_individual_list_rejects_bad_resolved(client: APIClient, db: None) -> None:
    resp = client.get("/api/job/jobs/delta-rejections/", {"resolved": "maybe"})
    assert resp.status_code == 400


def test_xero_individual_list_filters_by_resolved_and_app(
    client: APIClient, db: None
) -> None:
    open_err = XeroError.objects.create(message="sync failed", app="xero")
    done_err = XeroError.objects.create(message="resolved one", app="xero")
    done_err.resolved = True
    done_err.save(update_fields=["resolved"])
    XeroError.objects.create(message="other app", app="payroll")

    url = "/api/xero-errors/"

    unresolved = client.get(url, {"resolved": "false"})
    assert unresolved.status_code == 200
    unresolved_ids = {row["id"] for row in unresolved.json()["results"]}
    assert str(open_err.id) in unresolved_ids
    assert str(done_err.id) not in unresolved_ids

    by_app = client.get(url, {"app": "payroll"})
    assert by_app.status_code == 200
    assert {row["app"] for row in by_app.json()["results"]} == {"payroll"}
