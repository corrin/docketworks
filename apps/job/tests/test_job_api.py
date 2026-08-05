"""API tests for the job-core endpoints (django test Client, house pattern).

Guards the wire contract: auth split (any staff reads, office staff
mutates), the ETag/If-Match OCC flow (ADR 0003: 428 missing, 412 stale,
304 conditional GET, X-Resource-Version mirroring), the delta envelope
pipeline (ADR 0004), event dedup responses, and delta-rejection triage.
"""

import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.test import Client

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate
from apps.company.tests.job_fixtures import seed_job_prereqs
from apps.core.models import CompanyDefaults
from apps.job.models import Job, JobDeltaRejection
from apps.job.services.delta_checksum import compute_job_delta_checksum

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.job.tests.urls"),
]


def _get_etag(client: Client, job: Job) -> str:
    response = client.get(f"/api/job/jobs/{job.id}/header/")
    assert response.status_code == 200
    etag: str = response.headers["ETag"]
    return etag


def _envelope(job: Job, field: str, after: object) -> dict[str, object]:
    job.refresh_from_db()
    before = getattr(job, "status" if field == "job_status" else field)
    return {
        "change_id": str(uuid4()),
        "job_id": str(job.id),
        "fields": [field],
        "before": {field: before},
        "after": {field: after},
        "before_checksum": compute_job_delta_checksum(job.id, {field: before}, [field]),
    }


class TestAuth:
    def test_endpoints_require_auth(self, job: Job) -> None:
        anonymous = Client()
        assert anonymous.get(f"/api/job/jobs/{job.id}/").status_code == 401

    def test_workshop_staff_can_read_but_not_mutate(self, job: Job, workshop_staff: Staff) -> None:
        client = Client()
        authenticate(client, workshop_staff)

        assert client.get(f"/api/job/jobs/{job.id}/header/").status_code == 200
        response = client.put(
            f"/api/job/jobs/{job.id}/",
            data=_envelope(job, "description", "nope"),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_grouped_delta_rejections_are_office_only(self, workshop_staff: Staff) -> None:
        client = Client()
        authenticate(client, workshop_staff)
        assert client.get("/api/job/jobs/delta-rejections/grouped/").status_code == 403


class TestCreateJob:
    def test_create_returns_201_with_etag(self, client: Client, company: Company) -> None:
        response = client.post(
            "/api/job/jobs/",
            data={
                "name": "API Created Job",
                "company_id": str(company.id),
                "estimated_materials": "120.00",
                "estimated_time": "2.50",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["message"] == "Job created successfully"
        job = Job.objects.get(id=body["job_id"])
        assert job.name == "API Created Job"
        assert response.headers["ETag"].startswith('"job:')
        assert response.headers["X-Resource-Version"] == response.headers["ETag"]

    def test_create_for_disallowed_company_is_400(self, client: Client, company: Company) -> None:
        company.allow_jobs = False
        company.save(update_fields=["allow_jobs"])

        response = client.post(
            "/api/job/jobs/",
            data={
                "name": "Blocked Job",
                "company_id": str(company.id),
                "estimated_materials": "1.00",
                "estimated_time": "1.00",
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "not permitted for jobs" in response.json()["detail"]


class TestGetFullJob:
    def test_returns_v1_payload_shape_with_etag(
        self, client: Client, job: Job, company: Company
    ) -> None:
        response = client.get(f"/api/job/jobs/{job.id}/")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["job"]["company_name"] == company.name
        assert data["job"]["job_status"] == "draft"
        assert data["job"]["latest_actual"]["summary"]["profitMargin"] == 0.0
        assert data["company_defaults"].keys() == {
            "materials_markup",
            "time_markup",
            "wage_rate",
        }
        assert response.headers["ETag"].startswith('"job:')

    def test_conditional_get_returns_304(self, client: Client, job: Job) -> None:
        first = client.get(f"/api/job/jobs/{job.id}/")
        etag = first.headers["ETag"]

        second = client.get(f"/api/job/jobs/{job.id}/", HTTP_IF_NONE_MATCH=etag)

        assert second.status_code == 304
        assert second.headers["ETag"] == etag

    def test_unknown_job_is_400(self, client: Client) -> None:
        assert client.get(f"/api/job/jobs/{uuid4()}/").status_code == 400


class TestUpdateJob:
    def test_put_without_if_match_is_428(self, client: Client, job: Job) -> None:
        response = client.put(
            f"/api/job/jobs/{job.id}/",
            data=_envelope(job, "description", "New description"),
            content_type="application/json",
        )
        assert response.status_code == 428
        assert "If-Match" in response.json()["detail"]

    def test_put_with_stale_etag_is_412(self, client: Client, job: Job) -> None:
        response = client.put(
            f"/api/job/jobs/{job.id}/",
            data=_envelope(job, "description", "New description"),
            content_type="application/json",
            HTTP_IF_MATCH='"job:stale:etag"',
        )
        assert response.status_code == 412
        assert "Precondition failed" in response.json()["detail"]

    def test_put_with_valid_envelope_updates_and_returns_full_job(
        self, client: Client, job: Job
    ) -> None:
        etag = _get_etag(client, job)
        response = client.put(
            f"/api/job/jobs/{job.id}/",
            data=_envelope(job, "description", "Cut and fold"),
            content_type="application/json",
            HTTP_IF_MATCH=etag,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["job"]["description"] == "Cut and fold"
        job.refresh_from_db()
        assert job.description == "Cut and fold"
        # Fresh ETag reflects the new updated_at
        assert response.headers["ETag"] != etag
        assert response.headers["X-Resource-Version"] == response.headers["ETag"]

    def test_checksum_mismatch_hard_fail_is_412_and_recorded(
        self, client: Client, job: Job
    ) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.job_delta_soft_fail = False
        defaults.save(update_fields=["job_delta_soft_fail"])

        payload = _envelope(job, "description", "Edited elsewhere")
        payload["before_checksum"] = "stale-checksum"
        response = client.patch(
            f"/api/job/jobs/{job.id}/",
            data=payload,
            content_type="application/json",
            HTTP_IF_MATCH=_get_etag(client, job),
        )

        assert response.status_code == 412
        rejection = JobDeltaRejection.objects.get()
        assert str(rejection.change_id) == payload["change_id"]
        # Forensics: the submitting client's IP is stored on the rejection row.
        assert rejection.request_ip == "127.0.0.1"

    def test_negative_min_people_is_400(self, client: Client, job: Job) -> None:
        """Numeric bounds answer 400 at the boundary, not a DB CHECK 500."""
        response = client.put(
            f"/api/job/jobs/{job.id}/",
            data=_envelope(job, "min_people", -1),
            content_type="application/json",
            HTTP_IF_MATCH=_get_etag(client, job),
        )
        assert response.status_code == 400
        assert "cannot be negative" in response.json()["detail"]

    def test_non_envelope_body_is_422(self, client: Client, job: Job) -> None:
        response = client.put(
            f"/api/job/jobs/{job.id}/",
            data={"description": "Bare update"},
            content_type="application/json",
            HTTP_IF_MATCH=_get_etag(client, job),
        )
        # ninja request validation rejects the missing envelope fields
        assert response.status_code == 422


class TestDeleteJob:
    def test_delete_requires_if_match(self, client: Client, job: Job) -> None:
        assert client.delete(f"/api/job/jobs/{job.id}/").status_code == 428

    def test_delete_with_if_match_removes_job(self, client: Client, job: Job) -> None:
        response = client.delete(f"/api/job/jobs/{job.id}/", HTTP_IF_MATCH=_get_etag(client, job))

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert not Job.objects.filter(id=job.id).exists()


class TestJobHeader:
    def test_header_for_job_without_company(self, client: Client, office_staff: Staff) -> None:
        """Shell jobs have no company; every company/contact field must be null, not 500."""
        seed_job_prereqs()
        job = Job(name="Header Job", company=None)
        job.save(staff=office_staff)

        response = client.get(f"/api/job/jobs/{job.id}/header/")

        assert response.status_code == 200
        payload = response.json()
        assert payload["company_id"] is None
        assert payload["company_name"] is None
        assert payload["person_id"] is None
        assert payload["person_name"] is None

    def test_etag_round_trip_returns_304(self, client: Client, job: Job) -> None:
        first = client.get(f"/api/job/jobs/{job.id}/header/")
        etag = first.headers["ETag"]

        second = client.get(f"/api/job/jobs/{job.id}/header/", HTTP_IF_NONE_MATCH=etag)

        assert first.status_code == 200
        assert second.status_code == 304

    def test_missing_job_is_404_on_header_basic_info_and_events(self, client: Client) -> None:
        """Missing jobs map to 404 consistently on these three routes."""
        missing = uuid4()
        assert client.get(f"/api/job/jobs/{missing}/header/").status_code == 404
        assert client.get(f"/api/job/jobs/{missing}/basic-info/").status_code == 404
        assert client.get(f"/api/job/jobs/{missing}/events/").status_code == 404


class TestJobEvents:
    def _post_event(
        self, client: Client, job: Job, description: str
    ) -> "_MonkeyPatchedWSGIResponse":
        return client.post(
            f"/api/job/jobs/{job.id}/events/create/",
            data={"description": description},
            content_type="application/json",
            HTTP_IF_MATCH=_get_etag(client, job),
        )

    def test_create_event_returns_201_and_lists_it(self, client: Client, job: Job) -> None:
        response = self._post_event(client, job, "Called the customer")

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["event"]["description"] == "Called the customer"
        assert body["event"]["staff"] == "Office Staff"

        listing = client.get(f"/api/job/jobs/{job.id}/events/")
        assert listing.status_code == 200
        descriptions = [event["description"] for event in listing.json()["events"]]
        assert "Called the customer" in descriptions

    def test_rapid_repost_is_debounced_with_429(self, client: Client, job: Job) -> None:
        assert self._post_event(client, job, "Duplicate note").status_code == 201
        assert self._post_event(client, job, "Duplicate note").status_code == 429

    def test_duplicate_note_after_debounce_is_409(self, client: Client, job: Job) -> None:
        assert self._post_event(client, job, "Duplicate note").status_code == 201
        # Clear the debounce/duplicate cache keys; the service-level dedup
        # (JobEvent.create_safe) must still refuse the identical note.
        cache.clear()
        response = self._post_event(client, job, "Duplicate note")
        assert response.status_code == 409

    def test_missing_if_match_is_428(self, client: Client, job: Job) -> None:
        response = client.post(
            f"/api/job/jobs/{job.id}/events/create/",
            data={"description": "No precondition"},
            content_type="application/json",
        )
        assert response.status_code == 428


class TestUndoChange:
    def test_undo_round_trip(self, client: Client, job: Job) -> None:
        payload = _envelope(job, "description", "First edit")
        put = client.put(
            f"/api/job/jobs/{job.id}/",
            data=payload,
            content_type="application/json",
            HTTP_IF_MATCH=_get_etag(client, job),
        )
        assert put.status_code == 200

        undo = client.post(
            f"/api/job/jobs/{job.id}/undo-change/",
            data={"change_id": payload["change_id"]},
            content_type="application/json",
            HTTP_IF_MATCH=_get_etag(client, job),
        )

        assert undo.status_code == 200
        job.refresh_from_db()
        assert job.description is None


class TestTimelineAndBasicInfo:
    def test_timeline_lists_events(self, client: Client, job: Job) -> None:
        response = client.get(f"/api/job/jobs/{job.id}/timeline/")
        assert response.status_code == 200
        assert "timeline" in response.json()

    def test_basic_info_shape(self, client: Client, job: Job) -> None:
        response = client.get(f"/api/job/jobs/{job.id}/basic-info/")
        assert response.status_code == 200
        assert response.json().keys() == {
            "description",
            "delivery_date",
            "order_number",
            "notes",
        }

    def test_status_choices(self, client: Client) -> None:
        response = client.get("/api/job/jobs/status-choices/")
        assert response.status_code == 200
        assert response.json()["statuses"]["draft"] == "Draft"


class TestQuoteAccept:
    def test_accept_quote_moves_job_to_approved(self, client: Client, job: Job) -> None:
        response = client.post(
            f"/api/job/jobs/{job.id}/quote/accept/",
            HTTP_IF_MATCH=_get_etag(client, job),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        job.refresh_from_db()
        assert job.status == "approved"


def _fingerprint(reason: str) -> str:
    return hashlib.sha256(reason.encode("utf-8")).hexdigest()


class TestDeltaRejectionEndpoints:
    def test_grouped_list_returns_shape(self, client: Client) -> None:
        JobDeltaRejection.objects.create(reason="stale_etag", envelope={})
        JobDeltaRejection.objects.create(reason="stale_etag", envelope={})

        response = client.get("/api/job/jobs/delta-rejections/grouped/")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["results"][0]["reason"] == "stale_etag"
        assert body["results"][0]["occurrence_count"] == 2

    def test_resolve_cascades(self, client: Client) -> None:
        JobDeltaRejection.objects.create(reason="conflict", envelope={})
        JobDeltaRejection.objects.create(reason="conflict", envelope={})

        response = client.post(
            "/api/job/jobs/delta-rejections/grouped/mark_resolved/",
            data={"fingerprint": _fingerprint("conflict")},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json() == {"updated": 2}
        assert JobDeltaRejection.objects.filter(resolved=True).count() == 2

    def test_unresolve_cascades(self, client: Client) -> None:
        for _ in range(2):
            JobDeltaRejection.objects.create(reason="conflict", envelope={}, resolved=True)

        response = client.post(
            "/api/job/jobs/delta-rejections/grouped/mark_unresolved/",
            data={"fingerprint": _fingerprint("conflict")},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json() == {"updated": 2}

    def test_per_job_listing_filters_to_that_job(self, client: Client, job: Job) -> None:
        JobDeltaRejection.objects.create(job=job, reason="mine", envelope={})
        JobDeltaRejection.objects.create(reason="other", envelope={})

        response = client.get(f"/api/job/jobs/{job.id}/delta-rejections/")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["results"][0]["reason"] == "mine"
        assert body["results"][0]["job_name"] == job.name

    def test_admin_listing_returns_all(self, client: Client, job: Job) -> None:
        JobDeltaRejection.objects.create(job=job, reason="mine", envelope={})
        JobDeltaRejection.objects.create(reason="other", envelope={})

        response = client.get("/api/job/jobs/delta-rejections/")

        assert response.status_code == 200
        assert response.json()["count"] == 2
