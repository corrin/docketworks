"""API tests for CRM phone-call endpoints.

Django test Client with the HttpOnly JWT cookie (pattern:
apps/accounts/tests/test_auth_api.py). URLs are the production paths.
"""

import hashlib
import uuid
from pathlib import Path

import pytest
from django.http import StreamingHttpResponse
from django.test import Client
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.core.models import AppError, IntegrationSettings
from apps.crm.models import PhoneCallRecord, PhoneCallRecording, PhoneEndpoint
from apps.crm.tests.helpers import (
    PASSWORD,
    cookie_client,
    make_call,
    make_company,
    make_job,
    make_office_staff,
    make_recording,
)
from apps.job.models import Job

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.crm.tests.urls"),
]

CALLS_PATH = "/api/crm/phone-calls/"


@pytest.fixture
def office_staff() -> Staff:
    return make_office_staff("crm-link-office@example.com")


@pytest.fixture
def workshop_staff() -> Staff:
    return Staff.objects.create_user(
        office_email="crm-link-workshop@example.com",
        password=PASSWORD,
        is_office_staff=False,
    )


@pytest.fixture
def api(office_staff: Staff) -> Client:
    return cookie_client(office_staff)


@pytest.fixture
def company_obj() -> Company:
    return make_company("Phone Link Company")


@pytest.fixture
def other_company() -> Company:
    return make_company("Other Phone Link Company")


@pytest.fixture
def job(office_staff: Staff, company_obj: Company) -> Job:
    return make_job(company_obj, "Phone Link Job", office_staff)


@pytest.fixture
def other_job(office_staff: Staff, other_company: Company) -> Job:
    return make_job(other_company, "Other Phone Link Job", office_staff)


@pytest.fixture
def call(company_obj: Company) -> PhoneCallRecord:
    return make_call("call-1", company=company_obj)


class TestJobLink:
    """Office staff must be able to connect an imported phone call to the job
    it was about, while preventing cross-company history leaks.
    """

    def test_link_call_to_same_client_job_and_filter_by_job(
        self, api: Client, call: PhoneCallRecord, job: Job, office_staff: Staff
    ) -> None:
        response = api.post(
            f"{CALLS_PATH}{call.id}/job-link/",
            data={"job": str(job.id)},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["job"] == str(job.id)
        assert body["job_number"] == job.job_number
        assert body["job_name"] == job.name

        call.refresh_from_db()
        assert call.job == job
        assert call.job_linked_by == office_staff
        assert call.job_linked_at is not None

        filtered = api.get(CALLS_PATH, {"job": str(job.id)})

        assert filtered.status_code == 200
        assert filtered.json()["count"] == 1
        assert len(filtered.json()["results"]) == 1
        assert filtered.json()["results"][0]["id"] == str(call.id)

    def test_link_rejects_unmatched_call(self, api: Client, job: Job) -> None:
        unmatched = make_call("unmatched", company=None)

        response = api.post(
            f"{CALLS_PATH}{unmatched.id}/job-link/",
            data={"job": str(job.id)},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "assigned to a company" in response.json()["message"]

    def test_link_rejects_cross_company_job(
        self, api: Client, call: PhoneCallRecord, other_job: Job
    ) -> None:
        response = api.post(
            f"{CALLS_PATH}{call.id}/job-link/",
            data={"job": str(other_job.id)},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "same company" in response.json()["message"]

    def test_unlink_clears_job_metadata(
        self, api: Client, call: PhoneCallRecord, job: Job, office_staff: Staff
    ) -> None:
        call.job = job
        call.job_linked_by = office_staff
        call.job_linked_at = timezone.now()
        call.save(update_fields=["job", "job_linked_by", "job_linked_at"])

        response = api.delete(f"{CALLS_PATH}{call.id}/job-link/")

        assert response.status_code == 200
        assert response.json()["job"] is None
        call.refresh_from_db()
        assert call.job is None
        assert call.job_linked_by is None
        assert call.job_linked_at is None


class TestMalformedPathIdIsRejectedAtTheBoundary:
    """A non-UUID path id never reaches a service: it is a contract breach.

    Previously each endpoint decided for itself — the job-link routes passed the
    raw string down and came back with a business 400 "Phone call not found",
    while the retrieve routes ran it through a helper that raised 404. Both
    claimed the id was well-formed and merely unmatched, which was false. The
    path parameters are typed ``UUID`` now, so ninja rejects a malformed one
    with a 422 before any handler runs, identically on every endpoint.

    The 422 DOES write an AppError, which the sibling class asserts must not
    happen for service-level client errors. That split is real and pre-dates
    this change: the envelope persists every RequestValidationError
    (apps/core/envelope.py, ADR 0019) while service 400s persist nothing. It is
    open decision 3 in docs/rewrite-status.md — a client can now grow the
    AppError table with malformed URLs. Asserted rather than described, so
    whichever way that decision goes, this test fails and forces the update.
    """

    def test_malformed_call_id_on_link(self, api: Client, job: Job) -> None:
        response = api.post(
            f"{CALLS_PATH}not-a-uuid/job-link/",
            data={"job": str(job.id)},
            content_type="application/json",
        )

        assert response.status_code == 422

    def test_malformed_call_id_on_unlink(self, api: Client) -> None:
        response = api.delete(f"{CALLS_PATH}not-a-uuid/job-link/")

        assert response.status_code == 422

    def test_the_422_persists_an_app_error(self, api: Client) -> None:
        """Pins the current behaviour, which open decision 3 may reverse."""
        before = AppError.objects.count()

        response = api.delete(f"{CALLS_PATH}not-a-uuid/job-link/")

        assert response.status_code == 422
        assert AppError.objects.count() == before + 1

    def test_malformed_id_never_reaches_the_service(self, api: Client) -> None:
        """The 400 body proves a service ran; a 422 proves none did."""
        well_formed = api.delete(f"{CALLS_PATH}{uuid.uuid4()}/job-link/")
        malformed = api.delete(f"{CALLS_PATH}not-a-uuid/job-link/")

        assert well_formed.status_code == 400
        assert "Phone call not found" in well_formed.json()["message"]
        assert malformed.status_code == 422
        assert "message" not in malformed.json()


class TestClientErrorsDoNotPersistAppErrors:
    """Company typos are client errors, not server errors — no AppError rows."""

    def test_bad_call_id(self, api: Client, job: Job) -> None:
        before = AppError.objects.count()

        response = api.post(
            f"{CALLS_PATH}{uuid.uuid4()}/job-link/",
            data={"job": str(job.id)},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Phone call not found" in response.json()["message"]
        assert AppError.objects.count() == before

    def test_bad_job_id(self, api: Client, call: PhoneCallRecord) -> None:
        before = AppError.objects.count()

        response = api.post(
            f"{CALLS_PATH}{call.id}/job-link/",
            data={"job": str(uuid.uuid4())},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Job not found" in response.json()["message"]
        assert AppError.objects.count() == before

    def test_bad_call_id_on_unlink(self, api: Client) -> None:
        before = AppError.objects.count()

        response = api.delete(f"{CALLS_PATH}{uuid.uuid4()}/job-link/")

        assert response.status_code == 400
        assert "Phone call not found" in response.json()["message"]
        assert AppError.objects.count() == before

    def test_assign_number_bad_company_id(self, api: Client, call: PhoneCallRecord) -> None:
        call.external_number = "+6421555000"
        call.save(update_fields=["external_number"])
        before = AppError.objects.count()

        response = api.post(
            f"{CALLS_PATH}{call.id}/assign-number/",
            data={"company": str(uuid.uuid4())},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Company not found" in response.json()["message"]
        assert AppError.objects.count() == before

    def test_assign_number_cross_company_person(
        self,
        api: Client,
        call: PhoneCallRecord,
        company_obj: Company,
        other_company: Company,
    ) -> None:
        call.external_number = "+6421555001"
        call.save(update_fields=["external_number"])
        person = Person.objects.create(name="Other Contact")
        CompanyPersonLink.objects.create(company=other_company, person=person)
        before = AppError.objects.count()

        response = api.post(
            f"{CALLS_PATH}{call.id}/assign-number/",
            data={"company": str(company_obj.id), "person": str(person.id)},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Person is not linked to the selected company" in response.json()["message"]
        assert AppError.objects.count() == before


class TestCallList:
    """The CRM calls page must paginate and filter without drifting from the
    provider call fields.
    """

    @pytest.mark.usefixtures("call")
    def test_list_paginates_recent_calls(self, api: Client, company_obj: Company) -> None:
        """Catches CRM calls page regressions that fetch the full call archive."""
        make_call("call-2", company=company_obj)
        make_call("call-3", company=company_obj)

        response = api.get(CALLS_PATH, {"page_size": "2"})

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 3
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert body["total_pages"] == 2
        assert len(body["results"]) == 2

    @pytest.mark.usefixtures("call")
    def test_empty_list_uses_paginator_total_pages(self, api: Client, other_job: Job) -> None:
        response = api.get(CALLS_PATH, {"job": str(other_job.id)})

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert body["page"] == 1
        assert body["total_pages"] == 1
        assert body["results"] == []

    @pytest.mark.usefixtures("call")
    def test_list_page_size_is_capped(self, api: Client, company_obj: Company) -> None:
        """Catches accidental oversized phone-call responses."""
        for index in range(101):
            make_call(f"call-{index + 2}", company=company_obj)

        response = api.get(CALLS_PATH, {"page_size": "250"})

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 102
        assert body["page_size"] == 100
        assert len(body["results"]) == 100

    def test_list_filters_unmatched_and_unlinked_calls(
        self, api: Client, call: PhoneCallRecord, job: Job, company_obj: Company
    ) -> None:
        """Catches CRM queue regressions where triage tabs show the wrong work."""
        call.job = job
        call.save(update_fields=["job"])
        unlinked = make_call("unlinked", company=company_obj)
        unmatched = make_call("unmatched", company=None)

        unmatched_response = api.get(CALLS_PATH, {"company_match": "unmatched"})
        unlinked_response = api.get(
            CALLS_PATH, {"company_match": "matched", "job_link": "unlinked"}
        )

        assert unmatched_response.status_code == 200
        assert [row["id"] for row in unmatched_response.json()["results"]] == [str(unmatched.id)]
        assert unlinked_response.status_code == 200
        assert [row["id"] for row in unlinked_response.json()["results"]] == [str(unlinked.id)]

    def test_list_filters_by_direction_recording_date_and_search(
        self, api: Client, call: PhoneCallRecord, company_obj: Company
    ) -> None:
        """Catches recent-call filters drifting from provider call fields."""
        PhoneEndpoint.objects.update_or_create(
            normalized_number="+6496365131",
            defaults={
                "number": "+6496365131",
                "label": "Main line",
                "endpoint_type": PhoneEndpoint.EndpointType.MAIN_LINE,
                "is_active": True,
            },
        )
        recorded_call = call
        recorded_call.direction = PhoneCallRecord.Direction.INBOUND
        recorded_call.our_number = "+6496365131"
        recorded_call.external_number = recorded_call.origin
        recorded_call.save(update_fields=["direction", "our_number", "external_number"])
        PhoneCallRecording.objects.create(
            call=recorded_call,
            provider_recording_id="recording-filter",
            account_code="account",
            storage_path="recording-filter.mp3",
        )
        outbound = make_call(
            "outbound",
            company=company_obj,
            origin="+6496365131",
            destination="+6421555999",
        )
        outbound.direction = PhoneCallRecord.Direction.OUTBOUND
        outbound.our_number = outbound.origin
        outbound.external_number = outbound.destination
        outbound.save(update_fields=["direction", "our_number", "external_number"])

        response = api.get(
            CALLS_PATH,
            {
                "direction": "inbound",
                "has_recording": "true",
                "from_date": timezone.localdate().isoformat(),
                "to_date": timezone.localdate().isoformat(),
                "q": "Phone Link Company",
            },
        )

        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["id"] == str(recorded_call.id)

    def test_recording_download_url_is_same_origin_relative_path(
        self, api: Client, call: PhoneCallRecord
    ) -> None:
        """Catches proxy/ngrok auth failures from absolute localhost media links."""
        recording = PhoneCallRecording.objects.create(
            call=call,
            provider_recording_id="recording-relative-url",
            account_code="account",
            filename="recording-relative-url.mp3",
            storage_path="2026/06/02/recording-relative-url.mp3",
        )

        response = api.get(CALLS_PATH)

        assert response.status_code == 200
        row = response.json()["results"][0]
        assert (
            row["recording"]["download_url"]
            == f"/api/crm/phone-call-recordings/{recording.id}/download/"
        )
        assert "storage_path" not in row["recording"]


class TestRecordingDownload:
    """Recording playback must work off the local archive alone, revalidate by
    ETag, and surface a vanished file instead of hiding behind a 304.
    """

    @pytest.fixture(autouse=True)
    def storage_root(self, settings: SettingsWrapper, tmp_path: Path) -> Path:
        settings.PHONE_RECORDING_STORAGE_ROOT = str(tmp_path)
        return tmp_path

    def _archived_recording(
        self,
        call: PhoneCallRecord,
        root: Path,
        provider_recording_id: str,
        *,
        with_sha256: bool = True,
    ) -> tuple[PhoneCallRecording, bytes]:
        storage_path = f"2026/06/02/{provider_recording_id}.mp3"
        payload = b"\xff\xe3\x28\xc4recorded audio"
        full_path = root / storage_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(payload)
        recording = PhoneCallRecording.objects.create(
            call=call,
            provider_recording_id=provider_recording_id,
            account_code="account",
            filename=f"{provider_recording_id}.mp3",
            storage_path=storage_path,
            content_type="audio/mpeg",
            byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest() if with_sha256 else None,
            archived_at=timezone.now(),
        )
        return recording, payload

    def test_download_streams_archived_recording_without_provider_settings(
        self, api: Client, call: PhoneCallRecord, storage_root: Path
    ) -> None:
        """Catches LAN playback regressing to require provider connectivity."""
        IntegrationSettings.objects.filter(pk=1).update(
            phone_provider_downloads_enabled=False,
            phone_provider_recording_deletion_enabled=False,
            phone_provider_base_url=None,
            phone_provider_username=None,
            phone_provider_password=None,
            phone_provider_account_code=None,
        )
        recording, payload = self._archived_recording(
            call, storage_root, "offline-playback", with_sha256=False
        )

        response = api.get(f"/api/crm/phone-call-recordings/{recording.id}/download/")

        assert response.status_code == 200
        assert response["Content-Type"] == "audio/mpeg"
        assert isinstance(response, StreamingHttpResponse)
        assert response.getvalue() == payload

    def test_download_revalidates_with_etag_instead_of_resending(
        self, api: Client, call: PhoneCallRecord, storage_root: Path
    ) -> None:
        """Replaying a recording must not transfer the audio a second time."""
        recording, _payload = self._archived_recording(call, storage_root, "etag-playback")
        url = f"/api/crm/phone-call-recordings/{recording.id}/download/"

        first = api.get(url)

        assert first.status_code == 200
        etag = first["ETag"]

        second = api.get(url, headers={"if-none-match": etag})

        assert second.status_code == 304
        assert second.content == b""
        # The conditional response carries the validator it was matched on, so
        # the client can revalidate again without re-reading the body.
        assert second["ETag"] == etag

    def test_download_404s_a_missing_file_even_when_the_client_revalidates(
        self, api: Client, call: PhoneCallRecord, storage_root: Path
    ) -> None:
        """A vanished file must surface, not hide behind a 304."""
        recording, _payload = self._archived_recording(call, storage_root, "vanished")
        url = f"/api/crm/phone-call-recordings/{recording.id}/download/"
        etag = api.get(url)["ETag"]

        # Lost out of band: the row keeps its digest, the bytes are gone.
        (storage_root / str(recording.storage_path)).unlink()

        response = api.get(url, headers={"if-none-match": etag})

        assert response.status_code == 404

    def test_only_office_staff_can_read_recording_downloads(
        self, workshop_staff: Staff, call: PhoneCallRecord
    ) -> None:
        recording = make_recording(call, "workshop-staff-check", storage_path="ws-check.mp3")

        response = cookie_client(workshop_staff).get(
            f"/api/crm/phone-call-recordings/{recording.id}/download/"
        )

        assert response.status_code == 403
