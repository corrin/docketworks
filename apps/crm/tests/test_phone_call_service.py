import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)
from apps.crm.services.phone_call_service import (
    PhoneMatcher,
    PhoneProviderCallPage,
    PhoneProviderPortalClient,
    assign_phone_number,
    delete_archived_provider_recordings,
    link_phone_call_to_job,
    normalize_phone,
    rematch_calls_for_numbers,
    sync_call_history,
)
from apps.job.models import Job
from apps.testing import BaseAPITestCase, BaseTestCase
from apps.workflow.models import AppError, CompanyDefaults


class PhoneProviderPortalClientTests(SimpleTestCase):
    """Business case: provider call pagination can return intermittent empty
    pages. Stopping at the first empty page would silently miss billable
    customer calls later in the provider export.
    """

    def test_iter_call_pages_walks_pages_until_two_empty_pages(self) -> None:
        client = PhoneProviderPortalClient.__new__(PhoneProviderPortalClient)
        pages = {
            1: [{"id": "call-1"}],
            2: [{"id": "call-2"}],
            3: [],
            4: [{"id": "call-4"}],
            5: [],
            6: [],
        }

        def fake_fetch_cdr_page(*, page: int, start_date=None, end_date=None):
            return pages[page]

        client.fetch_cdr_page = fake_fetch_cdr_page

        results = list(client.iter_call_pages(page_delay=0))

        self.assertEqual(
            results,
            [
                PhoneProviderCallPage(page=1, calls=[{"id": "call-1"}]),
                PhoneProviderCallPage(page=2, calls=[{"id": "call-2"}]),
                PhoneProviderCallPage(page=4, calls=[{"id": "call-4"}]),
            ],
        )


class PhoneMatcherTests(SimpleTestCase):
    """Business case: the same NZ number appears in local, international, and
    spacing-heavy formats across CRM and call-provider exports. If these do not
    normalize to one value, calls stop attaching to the right customer.
    """

    def test_normalize_phone_matches_nz_variants_by_local_tail(self) -> None:
        self.assertEqual(normalize_phone("+64 9 636 5131"), "+6496365131")
        self.assertEqual(normalize_phone("6496365131"), "+6496365131")
        self.assertEqual(normalize_phone("09 636 5131"), "+6496365131")
        self.assertEqual(normalize_phone("027 530 3238"), "+64275303238")


class PhoneMatcherDatabaseTests(TestCase):
    """Business case: call records drive customer history. The matcher should
    attach calls when ownership is unambiguous, and refuse ambiguous matches so
    one client's calls are not shown under another client or contact.
    """

    def _client(self, name: str) -> Client:
        return Client.objects.create(name=name, xero_last_modified=timezone.now())

    def test_assign_phone_number_creates_primary_contact_method_and_matches_client(
        self,
    ) -> None:
        client = self._client("Acme Ltd")

        method = assign_phone_number(
            phone_number="09 636 5131",
            client_id=str(client.id),
            label="Reception",
        )
        matched_client, matched_contact = PhoneMatcher().match_customer(
            "+6496365131",
            "+6490000000",
        )

        self.assertEqual(method.normalized_value, "+6496365131")
        self.assertTrue(method.is_primary)
        self.assertEqual(matched_client, client)
        self.assertIsNone(matched_contact)

    def test_assign_number_allowed_on_contact_of_owning_client(self) -> None:
        """Assigning a client's number to one of its own contacts is not a conflict."""
        client = self._client("Acme Ltd")
        contact = ClientContact.objects.create(client=client, name="Jane Smith")
        assign_phone_number(phone_number="021 555 900", client_id=str(client.id))

        method = assign_phone_number(
            phone_number="021 555 900",
            client_id=str(client.id),
            contact_id=str(contact.id),
        )

        self.assertEqual(method.contact_id, contact.id)

    def test_assign_number_rejected_for_different_client(self) -> None:
        """A number owned by one client cannot be assigned to a different client."""
        owner = self._client("Acme Ltd")
        other = self._client("Beta Ltd")
        assign_phone_number(phone_number="021 555 901", client_id=str(owner.id))

        with self.assertRaisesRegex(ValueError, "already belongs"):
            assign_phone_number(phone_number="021 555 901", client_id=str(other.id))

    def test_single_contact_method_matches_contact(self) -> None:
        client = self._client("Acme Ltd")
        contact = ClientContact.objects.create(client=client, name="Jane Smith")
        ClientContactMethod.objects.create(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
            is_primary=True,
        )

        matched_client, matched_contact = PhoneMatcher().match_customer(
            "+6490000000",
            "+6421555123",
        )

        self.assertEqual(matched_client, client)
        self.assertEqual(matched_contact, contact)

    def test_same_number_across_contacts_on_one_client_is_allowed(
        self,
    ) -> None:
        """Two contacts of one client resolve to a single effective client owner."""
        client = self._client("Acme Ltd")
        jane = ClientContact.objects.create(client=client, name="Jane Smith")
        john = ClientContact.objects.create(client=client, name="John Smith")
        ClientContactMethod.objects.create(
            contact=jane,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        on_john = ClientContactMethod.objects.create(
            contact=john,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
        )

        matched_client, matched_contact = PhoneMatcher().match_customer("+6421555123")

        self.assertIsNotNone(on_john.pk)
        self.assertEqual(matched_client, client)
        self.assertIsNone(matched_contact)

    def test_same_number_across_clients_is_rejected(self) -> None:
        first = self._client("Acme Ltd")
        second = self._client("Beta Ltd")
        ClientContactMethod.objects.create(
            client=first,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
        )

        with self.assertRaises(ValidationError):
            ClientContactMethod.objects.create(
                client=second,
                method_type=ClientContactMethod.MethodType.PHONE,
                value="021 555 123",
            )

    def test_rematch_clears_job_link_when_number_moves_to_other_client(
        self,
    ) -> None:
        first = self._client("Acme Ltd")
        second = self._client("Beta Ltd")
        CompanyDefaults.objects.create(
            company_name="Test Company",
            shop_client=first,
        )
        staff = Staff.objects.create_user(
            email="rematch-link@example.com",
            password="testpass",
            is_office_staff=True,
        )
        job = Job.objects.create(client=first, name="Linked Job", staff=staff)
        ClientContactMethod.objects.create(
            client=second,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="+6421555123",
            normalized_value="+6421555123",
        )
        call_datetime = timezone.now()
        call = PhoneCallRecord.objects.create(
            provider_call_id="account:rematch-linked",
            account_code="account",
            call_datetime=call_datetime,
            call_date=timezone.localdate(),
            call_time=call_datetime.time(),
            origin="+6421555123",
            destination="+6490000000",
            client=first,
            job=job,
            job_linked_by=staff,
            job_linked_at=call_datetime,
            raw_json={
                "id": "rematch-linked",
                "calldate": timezone.localdate().isoformat(),
                "calltime": call_datetime.time().isoformat(timespec="seconds"),
            },
        )

        rematch_calls_for_numbers(["+6421555123"])

        call.refresh_from_db()
        self.assertEqual(call.client, second)
        self.assertIsNone(call.contact)
        self.assertIsNone(call.job)
        self.assertIsNone(call.job_linked_by)
        self.assertIsNone(call.job_linked_at)


class ProviderRecordingDeletionTests(TestCase):
    """Business case: provider recordings may be deleted only after DocketWorks
    has archived them locally and the retention window has passed. Deleting too
    early loses audit evidence; never deleting them grows provider storage.
    """

    def setUp(self) -> None:
        shop_client = Client.objects.create(
            name="Shop Client",
            xero_last_modified=timezone.now(),
        )
        CompanyDefaults.objects.create(
            company_name="Test Company",
            shop_client=shop_client,
        )
        PhoneProviderSettings.objects.update_or_create(
            pk=1,
            defaults={
                "base_url": "https://phone.example.test",
                "username": "user",
                "password": "secret",
                "account_code": "account",
            },
        )

    def test_deletes_only_downloaded_calls_more_than_one_month_old(self) -> None:
        now = timezone.now()
        old_call = self._call("old", now - timezone.timedelta(days=32))
        recent_call = self._call("recent", now - timezone.timedelta(days=15))
        not_downloaded_call = self._call(
            "not-downloaded", now - timezone.timedelta(days=45)
        )
        deleted_call = self._call("deleted", now - timezone.timedelta(days=50))

        old_recording = self._recording(old_call, "old", storage_path="old.mp3")
        self._recording(recent_call, "recent", storage_path="recent.mp3")
        self._recording(not_downloaded_call, "not-downloaded", storage_path="")
        self._recording(
            deleted_call,
            "deleted",
            storage_path="deleted.mp3",
            provider_deleted_at=now,
        )

        with patch(
            "apps.crm.services.phone_call_service.PhoneProviderPortalClient"
        ) as client_class:
            client = client_class.return_value
            result = delete_archived_provider_recordings(limit=100)

        self.assertEqual(result.candidates, 1)
        self.assertEqual(result.deleted, 1)
        self.assertEqual(result.failed, 0)
        client.login.assert_called_once_with()
        client.delete_recording.assert_called_once_with("old")

        old_recording.refresh_from_db()
        self.assertIsNotNone(old_recording.provider_deleted_at)
        self.assertEqual(old_recording.provider_delete_error, "")

    def _call(self, provider_id: str, call_datetime):
        return PhoneCallRecord.objects.create(
            provider_call_id=f"account:{provider_id}",
            account_code="account",
            call_datetime=call_datetime,
            call_date=timezone.localdate(call_datetime),
            call_time=call_datetime.time(),
            origin="+6496365131",
            destination="+6421467784",
            raw_json={
                "id": provider_id,
                "calldate": timezone.localdate(call_datetime).isoformat(),
                "calltime": call_datetime.time().isoformat(timespec="seconds"),
            },
        )

    def _recording(
        self,
        call: PhoneCallRecord,
        provider_recording_id: str,
        *,
        storage_path: str,
        provider_deleted_at=None,
    ):
        return PhoneCallRecording.objects.create(
            call=call,
            provider_recording_id=provider_recording_id,
            account_code="account",
            storage_path=storage_path,
            archived_at=timezone.now(),
            provider_deleted_at=provider_deleted_at,
        )


class PhoneCallSyncTests(BaseTestCase):
    """Business case: call imports are the source of CRM customer touchpoints.
    The supported provider path must be idempotent and preserve recording
    evidence without relying on the old standalone scraper.
    """

    def setUp(self) -> None:
        super().setUp()
        self.storage_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            PHONE_RECORDING_STORAGE_ROOT=self.storage_root.name
        )
        self.settings_override.enable()
        PhoneProviderSettings.objects.update_or_create(
            pk=1,
            defaults={
                "base_url": "https://phone.example.test",
                "username": "user",
                "password": "secret",
                "account_code": "account",
            },
        )

    def tearDown(self) -> None:
        self.settings_override.disable()
        self.storage_root.cleanup()
        super().tearDown()

    def test_sync_archives_recording_and_is_idempotent(self) -> None:
        client = Client.objects.create(
            name="Sync Client",
            xero_last_modified=timezone.now(),
        )
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        payload = self._payload()

        with patch(
            "apps.crm.services.phone_call_service.PhoneProviderPortalClient"
        ) as client_class:
            portal = client_class.return_value
            portal.iter_call_pages.return_value = [
                PhoneProviderCallPage(page=1, calls=[payload])
            ]
            portal.download_recording.return_value = (
                b"recorded audio",
                "call.mp3",
                "audio/mpeg",
            )

            first = sync_call_history()
            second = sync_call_history()

        self.assertEqual(first.calls_seen, 1)
        self.assertEqual(first.calls_saved, 1)
        self.assertEqual(first.recordings_seen, 1)
        self.assertEqual(first.recordings_archived, 1)
        self.assertEqual(second.calls_seen, 1)
        self.assertEqual(second.calls_saved, 0)
        self.assertEqual(second.recordings_archived, 0)
        self.assertEqual(PhoneCallRecord.objects.count(), 1)
        self.assertEqual(PhoneCallRecording.objects.count(), 1)

        call = PhoneCallRecord.objects.get()
        self.assertEqual(call.client, client)
        recording = call.recording
        self.assertEqual(recording.filename, "call.mp3")
        self.assertEqual(recording.byte_size, len(b"recorded audio"))
        self.assertTrue(recording.sha256)
        self.assertTrue(
            (Path(self.storage_root.name) / recording.storage_path).exists()
        )

    def test_recording_download_failure_persists_app_error(self) -> None:
        payload = self._payload(recording_id="broken-recording")

        with patch(
            "apps.crm.services.phone_call_service.PhoneProviderPortalClient"
        ) as client_class:
            portal = client_class.return_value
            portal.iter_call_pages.return_value = [
                PhoneProviderCallPage(page=1, calls=[payload])
            ]
            portal.download_recording.side_effect = ValueError("download failed")

            before = AppError.objects.count()
            result = sync_call_history()

        self.assertEqual(result.calls_seen, 1)
        self.assertEqual(result.recordings_seen, 1)
        self.assertEqual(result.recordings_archived, 0)
        self.assertEqual(AppError.objects.count(), before + 1)
        recording = PhoneCallRecording.objects.get()
        self.assertEqual(recording.archive_error, "download failed")
        self.assertFalse(recording.storage_path)

    def _payload(self, *, recording_id: str = "recording-1") -> dict[str, str]:
        return {
            "id": "provider-call-1",
            "calldate": "2026-06-01",
            "calltime": "10:11:12",
            "origin": "021 555 123",
            "destination": "09 636 5131",
            "seconds": "42",
            "charge": "0.1200",
            "type": "Inbound",
            "status": "Answered",
            "description": "Customer call",
            "RecordingId": recording_id,
        }


class PhoneCallJobLinkApiTests(BaseAPITestCase):
    """Business case: office staff must be able to connect an imported phone
    call to the job it was about, while preventing cross-client history leaks.
    """

    def setUp(self) -> None:
        super().setUp()
        self.storage_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            PHONE_RECORDING_STORAGE_ROOT=self.storage_root.name
        )
        self.settings_override.enable()
        self.office_staff = Staff.objects.create_user(
            email="crm-link-office@example.com",
            password="testpass",
            is_office_staff=True,
        )
        self.workshop_staff = Staff.objects.create_user(
            email="crm-link-workshop@example.com",
            password="testpass",
            is_office_staff=False,
            is_workshop_staff=True,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.office_staff)
        self.client_obj = Client.objects.create(
            name="Phone Link Client",
            xero_last_modified=timezone.now(),
        )
        self.other_client = Client.objects.create(
            name="Other Phone Link Client",
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            client=self.client_obj,
            name="Phone Link Job",
            staff=self.test_staff,
        )
        self.other_job = Job.objects.create(
            client=self.other_client,
            name="Other Phone Link Job",
            staff=self.test_staff,
        )
        self.call = self._call("call-1", client=self.client_obj)

    def tearDown(self) -> None:
        self.settings_override.disable()
        self.storage_root.cleanup()
        super().tearDown()

    def test_link_call_to_same_client_job_and_filter_by_job(self) -> None:
        response = self.api.post(
            f"/api/crm/phone-calls/{self.call.id}/job-link/",
            {"job": str(self.job.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["job"], self.job.id)
        self.assertEqual(response.data["job_number"], self.job.job_number)
        self.assertEqual(response.data["job_name"], self.job.name)

        self.call.refresh_from_db()
        self.assertEqual(self.call.job, self.job)
        self.assertEqual(self.call.job_linked_by, self.office_staff)
        self.assertIsNotNone(self.call.job_linked_at)

        filtered = self.api.get("/api/crm/phone-calls/", {"job": str(self.job.id)})

        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.data["count"], 1)
        self.assertEqual(len(filtered.data["results"]), 1)
        self.assertEqual(filtered.data["results"][0]["id"], str(self.call.id))

    def test_list_paginates_recent_calls(self) -> None:
        """Catches CRM calls page regressions that fetch the full call archive."""
        self._call("call-2", client=self.client_obj)
        self._call("call-3", client=self.client_obj)

        response = self.api.get("/api/crm/phone-calls/", {"page_size": "2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_size"], 2)
        self.assertEqual(response.data["total_pages"], 2)
        self.assertEqual(len(response.data["results"]), 2)

    def test_recording_download_url_is_same_origin_relative_path(self) -> None:
        """Catches proxy/ngrok auth failures from absolute localhost media links."""
        recording = PhoneCallRecording.objects.create(
            call=self.call,
            provider_recording_id="recording-relative-url",
            account_code="account",
            filename="recording-relative-url.mp3",
            storage_path="2026/06/02/recording-relative-url.mp3",
        )

        response = self.api.get("/api/crm/phone-calls/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["results"][0]["recording"]["download_url"],
            f"/api/crm/phone-call-recordings/{recording.id}/download/",
        )
        self.assertNotIn("storage_path", response.data["results"][0]["recording"])

    def test_empty_list_uses_paginator_total_pages(self) -> None:
        response = self.api.get(
            "/api/crm/phone-calls/", {"job": str(self.other_job.id)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["total_pages"], 1)
        self.assertEqual(response.data["results"], [])

    def test_list_page_size_is_capped(self) -> None:
        """Catches accidental oversized phone-call responses."""
        for index in range(101):
            self._call(f"call-{index + 2}", client=self.client_obj)

        response = self.api.get("/api/crm/phone-calls/", {"page_size": "250"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 102)
        self.assertEqual(response.data["page_size"], 100)
        self.assertEqual(len(response.data["results"]), 100)

    def test_list_filters_unmatched_and_unlinked_calls(self) -> None:
        """Catches CRM queue regressions where triage tabs show the wrong work."""
        linked = self.call
        linked.job = self.job
        linked.save(update_fields=["job", "updated_at"])
        unlinked = self._call("unlinked", client=self.client_obj)
        unmatched = self._call("unmatched", client=None)

        unmatched_response = self.api.get(
            "/api/crm/phone-calls/",
            {"client_match": "unmatched"},
        )
        unlinked_response = self.api.get(
            "/api/crm/phone-calls/",
            {"client_match": "matched", "job_link": "unlinked"},
        )

        self.assertEqual(unmatched_response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in unmatched_response.data["results"]],
            [str(unmatched.id)],
        )
        self.assertEqual(unlinked_response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in unlinked_response.data["results"]],
            [str(unlinked.id)],
        )

    def test_list_filters_by_direction_recording_date_and_search(self) -> None:
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
        recorded_call = self.call
        recorded_call.direction = PhoneCallRecord.Direction.INBOUND
        recorded_call.our_number = "+6496365131"
        recorded_call.external_number = recorded_call.origin
        recorded_call.save(
            update_fields=[
                "direction",
                "our_number",
                "external_number",
                "updated_at",
            ]
        )
        PhoneCallRecording.objects.create(
            call=recorded_call,
            provider_recording_id="recording-filter",
            account_code="account",
            storage_path="recording-filter.mp3",
        )
        outbound = self._call(
            "outbound",
            client=self.client_obj,
            origin="+6496365131",
            destination="+6421555999",
        )
        outbound.direction = PhoneCallRecord.Direction.OUTBOUND
        outbound.our_number = outbound.origin
        outbound.external_number = outbound.destination
        outbound.save(
            update_fields=[
                "direction",
                "our_number",
                "external_number",
                "updated_at",
            ]
        )

        response = self.api.get(
            "/api/crm/phone-calls/",
            {
                "direction": "inbound",
                "has_recording": "true",
                "from_date": timezone.localdate().isoformat(),
                "to_date": timezone.localdate().isoformat(),
                "q": "Phone Link Client",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(recorded_call.id))

    def test_bad_call_id_does_not_persist_app_error(self) -> None:
        """Catches client typos being treated as server errors."""
        before = AppError.objects.count()

        response = self.api.post(
            f"/api/crm/phone-calls/{uuid.uuid4()}/job-link/",
            {"job": str(self.job.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Phone call not found", response.data["message"])
        self.assertEqual(AppError.objects.count(), before)

    def test_malformed_call_id_does_not_persist_app_error(self) -> None:
        before = AppError.objects.count()

        response = self.api.post(
            "/api/crm/phone-calls/not-a-uuid/job-link/",
            {"job": str(self.job.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Phone call not found", response.data["message"])
        self.assertEqual(AppError.objects.count(), before)

    def test_bad_job_id_does_not_persist_app_error(self) -> None:
        """Catches client typos being treated as server errors."""
        before = AppError.objects.count()

        response = self.api.post(
            f"/api/crm/phone-calls/{self.call.id}/job-link/",
            {"job": str(uuid.uuid4())},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Job not found", response.data["message"])
        self.assertEqual(AppError.objects.count(), before)

    def test_service_rejects_malformed_job_id_as_client_error(self) -> None:
        with self.assertRaisesMessage(ValueError, "Job not found"):
            link_phone_call_to_job(
                call_id=str(self.call.id),
                job_id="not-a-uuid",
                linked_by=self.office_staff,
            )

    def test_bad_call_id_on_unlink_does_not_persist_app_error(self) -> None:
        """Catches client typos being treated as server errors."""
        before = AppError.objects.count()

        response = self.api.delete(f"/api/crm/phone-calls/{uuid.uuid4()}/job-link/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Phone call not found", response.data["message"])
        self.assertEqual(AppError.objects.count(), before)

    def test_malformed_call_id_on_unlink_does_not_persist_app_error(self) -> None:
        before = AppError.objects.count()

        response = self.api.delete("/api/crm/phone-calls/not-a-uuid/job-link/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Phone call not found", response.data["message"])
        self.assertEqual(AppError.objects.count(), before)

    def test_assign_number_bad_client_id_does_not_persist_app_error(self) -> None:
        self.call.external_number = "+6421555000"
        self.call.save(update_fields=["external_number", "updated_at"])
        before = AppError.objects.count()

        response = self.api.post(
            f"/api/crm/phone-calls/{self.call.id}/assign-number/",
            {
                "client": str(uuid.uuid4()),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Client not found", response.data["message"])
        self.assertEqual(AppError.objects.count(), before)

    def test_assign_number_cross_client_contact_does_not_persist_app_error(
        self,
    ) -> None:
        self.call.external_number = "+6421555001"
        self.call.save(update_fields=["external_number", "updated_at"])
        contact = ClientContact.objects.create(
            client=self.other_client,
            name="Other Contact",
        )
        before = AppError.objects.count()

        response = self.api.post(
            f"/api/crm/phone-calls/{self.call.id}/assign-number/",
            {
                "client": str(self.client_obj.id),
                "contact": str(contact.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Contact not found", response.data["message"])
        self.assertEqual(AppError.objects.count(), before)

    def test_link_rejects_unmatched_call(self) -> None:
        unmatched = self._call("unmatched", client=None)

        response = self.api.post(
            f"/api/crm/phone-calls/{unmatched.id}/job-link/",
            {"job": str(self.job.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("assigned to a client", response.data["message"])

    def test_link_rejects_cross_client_job(self) -> None:
        response = self.api.post(
            f"/api/crm/phone-calls/{self.call.id}/job-link/",
            {"job": str(self.other_job.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("same client", response.data["message"])

    def test_unlink_clears_job_metadata(self) -> None:
        self.call.job = self.job
        self.call.job_linked_by = self.office_staff
        self.call.job_linked_at = timezone.now()
        self.call.save(update_fields=["job", "job_linked_by", "job_linked_at"])

        response = self.api.delete(f"/api/crm/phone-calls/{self.call.id}/job-link/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["job"])
        self.call.refresh_from_db()
        self.assertIsNone(self.call.job)
        self.assertIsNone(self.call.job_linked_by)
        self.assertIsNone(self.call.job_linked_at)

    def test_download_streams_archived_recording_without_provider_settings(
        self,
    ) -> None:
        """Catches LAN playback regressing to require provider connectivity."""
        PhoneProviderSettings.objects.update_or_create(
            pk=1,
            defaults={
                "downloads_enabled": False,
                "recording_deletion_enabled": False,
                "base_url": None,
                "username": "",
                "password": "",
                "account_code": "",
            },
        )
        storage_path = "2026/06/02/offline-playback.mp3"
        payload = b"\xff\xe3\x28\xc4recorded audio"
        full_path = Path(self.storage_root.name) / storage_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(payload)
        recording = PhoneCallRecording.objects.create(
            call=self.call,
            provider_recording_id="offline-playback",
            account_code="account",
            filename="offline-playback.mp3",
            storage_path=storage_path,
            content_type="audio/mpeg",
            byte_size=len(payload),
            archived_at=timezone.now(),
        )

        response = self.api.get(
            f"/api/crm/phone-call-recordings/{recording.id}/download/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "audio/mpeg")
        assert isinstance(response, StreamingHttpResponse)
        body = b"".join(response.streaming_content)
        self.assertEqual(body, payload)

    def test_only_office_staff_can_read_recording_downloads(self) -> None:
        self.api.force_authenticate(user=self.workshop_staff)

        response = self.api.get("/api/crm/phone-calls/")

        self.assertEqual(response.status_code, 403)

    def _call(
        self,
        provider_id: str,
        *,
        client: Client | None,
        origin: str = "+6421555123",
        destination: str = "+6496365131",
    ) -> PhoneCallRecord:
        call_datetime = timezone.now()
        call_date = timezone.localdate()
        return PhoneCallRecord.objects.create(
            provider_call_id=f"account:{provider_id}",
            account_code="account",
            call_datetime=call_datetime,
            call_date=call_date,
            call_time=call_datetime.time(),
            origin=origin,
            destination=destination,
            client=client,
            raw_json={
                "id": provider_id,
                "calldate": call_date.isoformat(),
                "calltime": call_datetime.time().isoformat(timespec="seconds"),
            },
        )
