from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.crm.services.phone_call_service import (
    PhoneMatcher,
    PhoneProviderCallPage,
    PhoneProviderPortalClient,
    assign_phone_number,
    delete_archived_provider_recordings,
    normalize_phone,
)
from apps.workflow.models import CompanyDefaults


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
        matched_client, matched_contact = PhoneMatcher().match(
            "+6496365131",
            "+6490000000",
        )

        self.assertEqual(method.normalized_value, "+6496365131")
        self.assertTrue(method.is_primary)
        self.assertEqual(matched_client, client)
        self.assertIsNone(matched_contact)

    def test_single_contact_method_matches_contact(self) -> None:
        client = self._client("Acme Ltd")
        contact = ClientContact.objects.create(client=client, name="Jane Smith")
        ClientContactMethod.objects.create(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
            is_primary=True,
        )

        matched_client, matched_contact = PhoneMatcher().match(
            "+6490000000",
            "+6421555123",
        )

        self.assertEqual(matched_client, client)
        self.assertEqual(matched_contact, contact)

    def test_same_number_across_contacts_on_one_client_matches_client_only(
        self,
    ) -> None:
        client = self._client("Acme Ltd")
        jane = ClientContact.objects.create(client=client, name="Jane Smith")
        john = ClientContact.objects.create(client=client, name="John Smith")
        for contact in [jane, john]:
            ClientContactMethod.objects.create(
                contact=contact,
                method_type=ClientContactMethod.MethodType.PHONE,
                value="021 555 123",
            )

        matched_client, matched_contact = PhoneMatcher().match(
            "+6490000000",
            "+6421555123",
        )

        self.assertEqual(matched_client, client)
        self.assertIsNone(matched_contact)

    def test_same_number_across_clients_does_not_match(self) -> None:
        first = self._client("Acme Ltd")
        second = self._client("Beta Ltd")
        for client in [first, second]:
            ClientContactMethod.objects.create(
                client=client,
                method_type=ClientContactMethod.MethodType.PHONE,
                value="021 555 123",
            )

        matched_client, matched_contact = PhoneMatcher().match(
            "+6490000000",
            "+6421555123",
        )

        self.assertIsNone(matched_client)
        self.assertIsNone(matched_contact)


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
            phone_provider_base_url="https://phone.example.test",
            phone_provider_username="user",
            phone_provider_password="secret",
            phone_provider_account_code="account",
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
