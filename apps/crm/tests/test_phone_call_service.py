from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.crm.services.phone_call_service import (
    PhoneProviderCallPage,
    PhoneProviderPortalClient,
    delete_archived_provider_recordings,
    normalize_phone,
)
from apps.crm.tasks import delete_archived_phone_recordings_task, sync_phone_calls_task


class PhoneProviderPortalClientTests(SimpleTestCase):
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
    def test_normalize_phone_matches_nz_variants_by_local_tail(self) -> None:
        self.assertEqual(normalize_phone("+64 9 636 5131"), "+6496365131")
        self.assertEqual(normalize_phone("6496365131"), "+6496365131")
        self.assertEqual(normalize_phone("09 636 5131"), "+6496365131")
        self.assertEqual(normalize_phone("027 530 3238"), "+64275303238")


class PhoneCallTaskTests(SimpleTestCase):
    @override_settings(PHONE_CALL_DOWNLOADS_ENABLED=False)
    def test_sync_task_skips_when_downloads_disabled(self) -> None:
        with patch("apps.crm.services.phone_call_service.sync_recent_calls") as sync:
            sync_phone_calls_task()

        sync.assert_not_called()

    @override_settings(PHONE_PROVIDER_RECORDING_DELETION_ENABLED=False)
    def test_delete_task_skips_when_provider_deletion_disabled(self) -> None:
        with patch(
            "apps.crm.services.phone_call_service.delete_archived_provider_recordings"
        ) as delete_recordings:
            delete_archived_phone_recordings_task()

        delete_recordings.assert_not_called()


class ProviderRecordingDeletionTests(TestCase):
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
            call_date=call_datetime.date(),
            call_time=call_datetime.time(),
            origin="+6496365131",
            destination="+6421467784",
            raw_json={
                "id": provider_id,
                "calldate": call_datetime.date().isoformat(),
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
