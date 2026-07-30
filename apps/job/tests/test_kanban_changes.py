"""Incremental Kanban freshness must update only the affected board structure."""

from datetime import timedelta
from typing import Protocol, TypedDict

from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.etag import generate_job_etag
from apps.job.models import Job
from apps.testing import BaseAPITestCase
from apps.workflow.models import AppError, XeroPayItem


class KanbanCardPayload(TypedDict):
    id: str
    name: str


class KanbanChangesPayload(TypedDict):
    jobs: list[KanbanCardPayload]
    removed_job_ids: list[str]
    full_refresh_required: bool


class KanbanChangesTestResponse(Protocol):
    status_code: int

    def json(self) -> KanbanChangesPayload: ...


class KanbanChangesAPITests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(self.test_staff)
        self.company = Company.objects.create(
            name="Kanban Changes Company",
            xero_last_modified=timezone.now(),
        )
        self.pay_item = XeroPayItem.get_ordinary_time()
        self.first_job = self._create_job("First changed-card job", 9101)
        self.second_job = self._create_job("Second changed-card job", 9102)

    def _create_job(self, name: str, job_number: int) -> Job:
        created_job: object = Job.objects.create(
            name=name,
            job_number=job_number,
            company=self.company,
            status="in_progress",
            created_by=self.test_staff,
            default_xero_pay_item=self.pay_item,
            staff=self.test_staff,
        )
        if not isinstance(created_job, Job):
            raise TypeError("Job manager returned a non-Job instance")
        return created_job

    def _kanban_version(self) -> str:
        response = self.client.get("/api/data-versions/")
        self.assertEqual(response.status_code, 200)
        payload: object = response.json()
        if not isinstance(payload, dict):
            self.fail("Data versions response must be an object")
        kanban_version: object = payload.get("kanban")
        if not isinstance(kanban_version, str):
            self.fail("Data versions response must contain a string Kanban version")
        return kanban_version

    def _changes_after(self, version: str) -> KanbanChangesTestResponse:
        return self.client.get(
            "/api/job/jobs/kanban-changes/",
            {"after": version},
        )

    def test_returns_only_the_changed_card_when_membership_is_unchanged(self) -> None:
        version = self._kanban_version()
        self.first_job.name = "Renamed first job"
        self.first_job.save(staff=self.test_staff, update_fields=["name"])

        response = self._changes_after(version)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["full_refresh_required"])
        self.assertEqual(
            [job["id"] for job in payload["jobs"]],
            [str(self.first_job.id)],
        )
        self.assertEqual(payload["jobs"][0]["name"], "Renamed first job")
        self.assertEqual(payload["removed_job_ids"], [])

    def test_reports_a_card_removed_when_it_moves_to_hidden_status(self) -> None:
        version = self._kanban_version()
        self.first_job.status = "special"
        self.first_job.save(staff=self.test_staff, update_fields=["status"])

        response = self._changes_after(version)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["full_refresh_required"])
        self.assertEqual(payload["jobs"], [])
        self.assertEqual(payload["removed_job_ids"], [str(self.first_job.id)])

    def test_requires_full_refresh_when_job_count_changes(self) -> None:
        version = self._kanban_version()
        self._create_job("Newly created job", 9103)

        response = self._changes_after(version)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["full_refresh_required"])
        self.assertEqual(payload["jobs"], [])
        self.assertEqual(payload["removed_job_ids"], [])

    def test_requires_full_refresh_for_count_neutral_delete_and_create(self) -> None:
        version = self._kanban_version()
        self.first_job.delete()
        replacement = self._create_job("Replacement job", 9103)

        response = self._changes_after(version)

        self.assertEqual(Job.objects.count(), 2)
        self.assertTrue(response.json()["full_refresh_required"])
        self.assertTrue(Job.objects.filter(pk=replacement.pk).exists())

    def test_rejects_missing_or_malformed_version(self) -> None:
        missing = self.client.get("/api/job/jobs/kanban-changes/")
        malformed = self.client.get(
            "/api/job/jobs/kanban-changes/",
            {"after": "not-a-version"},
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        self.assertIn("error_id", malformed.json()["details"])
        self.assertEqual(AppError.objects.count(), 1)


class ManualJobEventETagTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.office_staff = Staff.objects.create_user(
            email="etag-office@example.test",
            password="testpass",
            first_name="ETag",
            last_name="Office",
            is_office_staff=True,
        )
        self.client.force_authenticate(self.office_staff)
        company = Company.objects.create(
            name="ETag Event Company",
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            name="ETag Event Job",
            job_number=9201,
            company=company,
            status="in_progress",
            created_by=self.office_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.office_staff,
        )
        self.detail_url = f"/api/job/jobs/{self.job.id}/"
        self.event_url = f"/api/job/jobs/{self.job.id}/events/create/"

    def _current_etag(self) -> str:
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        return response["ETag"]

    def test_event_requires_if_match(self) -> None:
        response = self.client.post(
            self.event_url,
            {"description": "No precondition"},
            format="json",
        )

        self.assertEqual(response.status_code, 428)
        self.assertEqual(self.job.events.filter(event_type="manual_note").count(), 0)

    def test_event_rejects_stale_etag_without_creating_an_event(self) -> None:
        stale_etag = self._current_etag()
        self.job.name = "Concurrent rename"
        self.job.save(staff=self.office_staff, update_fields=["name"])

        response = self.client.post(
            self.event_url,
            {"description": "Stale note"},
            format="json",
            HTTP_IF_MATCH=stale_etag,
        )

        self.assertEqual(response.status_code, 412)
        self.assertEqual(self.job.events.filter(event_type="manual_note").count(), 0)

    def test_event_bumps_job_etag_and_updated_at(self) -> None:
        original_updated_at = self.job.updated_at
        original_etag = self._current_etag()

        response = self.client.post(
            self.event_url,
            {"description": "Fresh note"},
            format="json",
            HTTP_IF_MATCH=original_etag,
        )

        self.assertEqual(response.status_code, 201)
        self.job.refresh_from_db()
        self.assertGreater(self.job.updated_at, original_updated_at)
        self.assertNotEqual(response["ETag"], original_etag)
        self.assertFalse(response["ETag"].startswith("W/"))

    def test_event_rejects_a_weak_if_match_tag(self) -> None:
        current_etag = self._current_etag()

        response = self.client.post(
            self.event_url,
            {"description": "Weak precondition"},
            format="json",
            HTTP_IF_MATCH=f"W/{current_etag}",
        )

        self.assertEqual(response.status_code, 412)
        self.assertIn("error_id", response.json()["details"])

    def test_job_etag_distinguishes_changes_within_one_millisecond(self) -> None:
        first_timestamp = self.job.updated_at
        self.job.updated_at = first_timestamp + timedelta(microseconds=100)

        later_etag = generate_job_etag(self.job)
        self.job.updated_at = first_timestamp

        self.assertNotEqual(generate_job_etag(self.job), later_etag)
