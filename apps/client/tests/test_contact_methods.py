from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

if TYPE_CHECKING:
    from apps.job.models import Job

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.crm.models import PhoneCallRecord
from apps.crm.services.phone_call_service import rematch_calls_for_numbers
from apps.testing import BaseAPITestCase, BaseTestCase
from apps.workflow.accounting.types import ContactResult


class ClientContactMethodTests(TestCase):
    def _client(self, name: str = "Acme Ltd") -> Client:
        return Client.objects.create(name=name, xero_last_modified=timezone.now())

    def test_phone_normalization_matches_nz_variants(self) -> None:
        """Catches call matching failures when NZ local and E.164 numbers diverge."""
        self.assertEqual(
            ClientContactMethod.normalize_phone("+64 9 636 5131"),
            "+6496365131",
        )
        self.assertEqual(
            ClientContactMethod.normalize_phone("09 636 5131"),
            "+6496365131",
        )

    def test_primary_phone_is_single_per_client_owner(self) -> None:
        """Catches multiple primary phone numbers being left on a client record."""
        client = self._client()
        first = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )
        second = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 222 2222",
            is_primary=True,
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)

    def test_same_number_allowed_on_client_and_its_own_contact(self) -> None:
        """A client and its own contact sharing one line must not be rejected."""
        client = self._client()
        contact = ClientContact.objects.create(client=client, name="Jane Smith")
        on_client = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        on_contact = ClientContactMethod.objects.create(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )

        self.assertEqual(on_client.normalized_value, on_contact.normalized_value)
        self.assertIsNotNone(on_contact.pk)

    def test_same_number_allowed_on_two_contacts_of_same_client(self) -> None:
        """Two contacts of one client can share a number (one effective client)."""
        client = self._client()
        first_contact = ClientContact.objects.create(client=client, name="A")
        second_contact = ClientContact.objects.create(client=client, name="B")
        ClientContactMethod.objects.create(
            contact=first_contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        on_second = ClientContactMethod.objects.create(
            contact=second_contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )

        self.assertIsNotNone(on_second.pk)

    def test_same_number_rejected_across_different_clients(self) -> None:
        """Two different clients cannot own one number; the matcher would be ambiguous."""
        client_a = self._client("Acme Ltd")
        client_b = self._client("Beta Ltd")
        ClientContactMethod.objects.create(
            client=client_a,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        with self.assertRaises(ValidationError):
            ClientContactMethod.objects.create(
                client=client_b,
                method_type=ClientContactMethod.MethodType.PHONE,
                value="021 111 111",
            )

    def test_same_number_rejected_across_contacts_of_different_clients(self) -> None:
        """Contacts of two different clients cannot share a number."""
        client_a = self._client("Acme Ltd")
        client_b = self._client("Beta Ltd")
        contact_a = ClientContact.objects.create(client=client_a, name="A")
        contact_b = ClientContact.objects.create(client=client_b, name="B")
        ClientContactMethod.objects.create(
            contact=contact_a,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        with self.assertRaises(ValidationError):
            ClientContactMethod.objects.create(
                contact=contact_b,
                method_type=ClientContactMethod.MethodType.PHONE,
                value="021 111 111",
            )

    def test_grandfathered_cross_client_number_can_be_resaved(self) -> None:
        """A pre-existing cross-client number (legacy data) re-saves unchanged."""
        client_a = self._client("Acme Ltd")
        client_b = self._client("Beta Ltd")
        ClientContactMethod.objects.create(
            client=client_a,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        # Simulate legacy prod data: B already owns the same number, inserted
        # bypassing the guard (as pre-guard rows were).
        legacy = ClientContactMethod(
            client=client_b,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        legacy.normalized_value = ClientContactMethod.normalize_phone("021 111 111")
        ClientContactMethod.objects.bulk_create([legacy])

        legacy.refresh_from_db()
        legacy.label = "Mobile"
        legacy.save()  # association unchanged -> grandfathered, must not raise

        legacy.refresh_from_db()
        self.assertEqual(legacy.label, "Mobile")

    def test_changing_number_into_another_clients_ownership_raises(self) -> None:
        """Editing a method's number onto another client's number is blocked."""
        client_a = self._client("Acme Ltd")
        client_b = self._client("Beta Ltd")
        ClientContactMethod.objects.create(
            client=client_a,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        moving = ClientContactMethod.objects.create(
            client=client_b,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 222 222",
        )

        moving.value = "021 111 111"  # now collides with client A
        with self.assertRaises(ValidationError):
            moving.save()

    def test_primary_phone_is_single_per_contact_owner(self) -> None:
        """Catches multiple primary phone numbers being left on a contact record."""
        client = self._client()
        contact = ClientContact.objects.create(client=client, name="Jane Smith")
        first = ClientContactMethod.objects.create(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
            is_primary=True,
        )
        second = ClientContactMethod.objects.create(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 222 222",
            is_primary=True,
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)

    def test_partial_update_fields_still_persists_normalized_value(self) -> None:
        """save(update_fields=["value"]) must also persist the recomputed
        normalized_value, or the matching/uniqueness index goes stale."""
        client = self._client("Acme Ltd")
        method = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )

        method.value = "021 222 222"
        method.save(update_fields=["value"])

        method.refresh_from_db()
        self.assertEqual(
            method.normalized_value,
            ClientContactMethod.normalize_phone("021 222 222"),
        )


class ClientPrimaryPhoneValueTests(TestCase):
    """Guards the helper PO PDFs and Xero sync use to print a supplier phone."""

    def test_returns_primary_phone_first(self) -> None:
        client = Client.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
        )
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 222 2222",
            is_primary=True,
        )

        self.assertEqual(client.primary_phone_value(), "09 222 2222")

    def test_returns_empty_string_when_no_phone_methods(self) -> None:
        client = Client.objects.create(
            name="Phoneless Ltd", xero_last_modified=timezone.now()
        )
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.EMAIL,
            value="office@example.com",
        )

        self.assertEqual(client.primary_phone_value(), "")


class PrimaryPhoneAnnotationTests(TestCase):
    """Guards the shared queryset annotation every phone-bearing payload uses."""

    def _client(self, name: str = "Acme Ltd") -> Client:
        return Client.objects.create(name=name, xero_last_modified=timezone.now())

    def test_client_annotation_prefers_primary_over_label_order(self) -> None:
        client = self._client()
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            label="AAA sorts first",
        )
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 222 2222",
            label="ZZZ sorts last",
            is_primary=True,
        )

        annotated = Client.objects.annotate(
            phone=ClientContactMethod.primary_phone_annotation(
                owner="client", outer_ref="pk"
            )
        ).get(pk=client.pk)

        self.assertEqual(annotated.phone, "09 222 2222")

    def test_client_annotation_is_empty_string_without_phones(self) -> None:
        client = self._client("Phoneless Ltd")
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.EMAIL,
            value="office@example.com",
        )

        annotated = Client.objects.annotate(
            phone=ClientContactMethod.primary_phone_annotation(
                owner="client", outer_ref="pk"
            )
        ).get(pk=client.pk)

        self.assertEqual(annotated.phone, "")

    def test_contact_annotation_returns_contact_primary_phone(self) -> None:
        client = self._client()
        contact = ClientContact.objects.create(client=client, name="Jane Smith")
        ClientContactMethod.objects.create(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 111 111",
        )
        ClientContactMethod.objects.create(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 222 222",
            is_primary=True,
        )

        annotated = ClientContact.objects.annotate(
            phone=ClientContactMethod.primary_phone_annotation(
                owner="contact", outer_ref="pk"
            )
        ).get(pk=contact.pk)

        self.assertEqual(annotated.phone, "021 222 222")


class UpdateJobContactTests(BaseTestCase):
    """Guards that reassigning a job's contact persists to the job record."""

    def _job_with_contact(self) -> "tuple[Job, Client, ClientContact]":
        from apps.job.models import Job
        from apps.workflow.models import XeroPayItem

        client = Client.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )
        contact = ClientContact.objects.create(client=client, name="Jane Smith")
        job: Job = Job.objects.create(
            name="Contact Assignment Job",
            client=client,
            contact=contact,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )
        return job, client, contact

    def test_update_job_contact_persists_new_contact(self) -> None:
        from apps.client.services.client_rest_service import ClientRestService

        job, client, _ = self._job_with_contact()
        new_contact = ClientContact.objects.create(client=client, name="Bob Brown")

        ClientRestService.update_job_contact(
            job.id, {"id": str(new_contact.id)}, self.test_staff
        )

        job.refresh_from_db()
        self.assertEqual(job.contact_id, new_contact.id)


class ClientListPhoneTests(TestCase):
    """Guards the Phone column of the clients list (restored after the
    ClientContactMethod migration dropped it)."""

    def _client_with_phone(self, name: str, phone: str) -> Client:
        client = Client.objects.create(name=name, xero_last_modified=timezone.now())
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value=phone,
            is_primary=True,
        )
        return client

    def _lazy_phone_queries(self, captured: CaptureQueriesContext) -> list[str]:
        return [
            q["sql"]
            for q in captured.captured_queries
            if q["sql"].startswith('SELECT "client_clientcontactmethod"')
        ]

    def test_list_clients_rows_include_phone(self) -> None:
        from apps.client.services.client_rest_service import ClientRestService

        self._client_with_phone("Acme Ltd", "09 111 1111")
        Client.objects.create(name="Phoneless Ltd", xero_last_modified=timezone.now())

        with CaptureQueriesContext(connection) as captured:
            result = ClientRestService.list_clients(page=1, page_size=10)

        phones = {row["name"]: row["phone"] for row in result["results"]}
        self.assertEqual(phones["Acme Ltd"], "09 111 1111")
        self.assertEqual(phones["Phoneless Ltd"], "")
        self.assertEqual(self._lazy_phone_queries(captured), [])

    def test_searched_clients_include_phone(self) -> None:
        from apps.client.services.client_rest_service import ClientRestService

        self._client_with_phone("Acme Ltd", "09 111 1111")

        result = ClientRestService.list_clients(query="Acme", page=1, page_size=10)

        self.assertEqual(result["results"][0]["phone"], "09 111 1111")


class ClientContactApiPhoneTests(BaseAPITestCase):
    """Guards the contact phone read/write restored on the contacts endpoint
    (client detail Contacts card, ContactSelectionModal, contact picker)."""

    URL = "/api/clients/contacts/"

    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)
        self.job_client = Client.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )

    def _contact(
        self, name: str = "Jane Smith", phone: str | None = None
    ) -> ClientContact:
        contact = ClientContact.objects.create(client=self.job_client, name=name)
        if phone is not None:
            ClientContactMethod.objects.create(
                contact=contact,
                method_type=ClientContactMethod.MethodType.PHONE,
                value=phone,
                is_primary=True,
            )
        return contact

    def test_list_includes_contact_phone_without_lazy_queries(self) -> None:
        self._contact("Jane Smith", phone="021 111 111")
        self._contact("No Phone")

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(self.URL, {"client_id": str(self.job_client.id)})

        self.assertEqual(response.status_code, 200)
        phones = {row["name"]: row["phone"] for row in response.json()}
        self.assertEqual(phones["Jane Smith"], "021 111 111")
        self.assertEqual(phones["No Phone"], "")
        lazy = [
            q["sql"]
            for q in captured.captured_queries
            if q["sql"].startswith('SELECT "client_clientcontactmethod"')
        ]
        self.assertEqual(lazy, [])

    def test_create_contact_with_phone_creates_primary_method(self) -> None:
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    self.URL,
                    {
                        "client": str(self.job_client.id),
                        "name": "Bob Brown",
                        "phone": "021 222 222",
                    },
                    format="json",
                )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["phone"], "021 222 222")
        method = ClientContactMethod.objects.get(contact__name="Bob Brown")
        self.assertEqual(method.method_type, ClientContactMethod.MethodType.PHONE)
        self.assertTrue(method.is_primary)
        rematch.assert_called_once_with(["+6421222222"])

    def test_update_phone_updates_existing_primary_method(self) -> None:
        contact = self._contact("Jane Smith", phone="021 111 111")
        method = contact.contact_methods.get()

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    f"{self.URL}{contact.id}/",
                    {"phone": "021 333 333"},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "021 333 333")
        method.refresh_from_db()
        self.assertEqual(method.value, "021 333 333")
        self.assertEqual(contact.contact_methods.count(), 1)
        rematch.assert_called_once_with(["+6421111111", "+6421333333"])

    def test_update_phone_matching_secondary_promotes_it(self) -> None:
        contact = self._contact("Jane Smith", phone="021 111 111")
        secondary = ClientContactMethod.objects.create(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 444 444",
        )

        response = self.client.patch(
            f"{self.URL}{contact.id}/",
            {"phone": "021 444 444"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        secondary.refresh_from_db()
        self.assertTrue(secondary.is_primary)
        self.assertEqual(contact.contact_methods.filter(is_primary=True).count(), 1)

    def test_blank_phone_leaves_methods_untouched(self) -> None:
        contact = self._contact("Jane Smith", phone="021 111 111")

        response = self.client.patch(
            f"{self.URL}{contact.id}/",
            {"phone": "", "position": "Manager"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "021 111 111")
        self.assertEqual(contact.contact_methods.count(), 1)

    def test_conflicting_phone_returns_400_and_creates_nothing(self) -> None:
        other_client = Client.objects.create(
            name="Beta Ltd", xero_last_modified=timezone.now()
        )
        ClientContactMethod.objects.create(
            client=other_client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 555",
        )
        contact = self._contact("Jane Smith")

        response = self.client.patch(
            f"{self.URL}{contact.id}/",
            {"phone": "021 555 555"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.json())
        self.assertEqual(contact.contact_methods.count(), 0)


class ClientUpdatePhoneTests(BaseAPITestCase):
    """Guards the phone edit restored on the Edit Client modal's update flow
    (client detail's "phone" read via ClientContactMethod, written through
    set_primary_phone)."""

    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.test_staff)

    def _client(self, name: str = "Acme Ltd") -> Client:
        return Client.objects.create(name=name, xero_last_modified=timezone.now())

    def _update_url(self, client_id) -> str:
        return f"/api/clients/{client_id}/update/"

    def test_update_with_new_phone_creates_primary_method(self) -> None:
        client = self._client()

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    self._update_url(client.id),
                    {"phone": "09 111 1111"},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client"]["phone"], "09 111 1111")
        method = ClientContactMethod.objects.get(client=client)
        self.assertEqual(method.method_type, ClientContactMethod.MethodType.PHONE)
        self.assertEqual(method.value, "09 111 1111")
        self.assertTrue(method.is_primary)
        rematch.assert_called_once_with(
            [ClientContactMethod.normalize_phone("09 111 1111")]
        )

    def test_update_with_existing_secondary_number_promotes_it(self) -> None:
        client = self._client()
        primary = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )
        secondary = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 222 2222",
        )

        response = self.client.patch(
            self._update_url(client.id), {"phone": "09 222 2222"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        primary.refresh_from_db()
        secondary.refresh_from_db()
        self.assertFalse(primary.is_primary)
        self.assertTrue(secondary.is_primary)
        self.assertEqual(client.contact_methods.count(), 2)

    def test_update_renumbers_current_primary_when_number_is_new(self) -> None:
        """Matches set_primary_phone's contract: a genuinely new number reuses
        (renumbers) the existing primary row instead of creating a second
        one."""
        client = self._client()
        primary = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )

        response = self.client.patch(
            self._update_url(client.id), {"phone": "09 333 3333"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.contact_methods.count(), 1)
        primary.refresh_from_db()
        self.assertEqual(primary.value, "09 333 3333")
        self.assertTrue(primary.is_primary)

    def test_blank_phone_clears_primary_method(self) -> None:
        client = self._client()
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )

        with patch(
            "apps.client.services.client_rest_service.rematch_phone_calls_task.delay"
        ) as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    self._update_url(client.id),
                    {"phone": "", "name": "Acme Renamed"},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client"]["phone"], "")
        self.assertEqual(client.contact_methods.count(), 0)
        client.refresh_from_db()
        self.assertEqual(client.name, "Acme Renamed")
        rematch.assert_called_once_with(
            [ClientContactMethod.normalize_phone("09 111 1111")]
        )

    def test_omitted_phone_leaves_methods_untouched(self) -> None:
        client = self._client()
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )

        with patch(
            "apps.client.services.client_rest_service.rematch_phone_calls_task.delay"
        ) as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    self._update_url(client.id),
                    {"name": "Acme Renamed"},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client"]["phone"], "09 111 1111")
        self.assertEqual(client.contact_methods.count(), 1)
        client.refresh_from_db()
        self.assertEqual(client.name, "Acme Renamed")
        rematch.assert_not_called()

    def test_conflicting_phone_returns_400_and_rolls_back_update(self) -> None:
        """A conflict must not leave the update half-applied: neither the new
        name nor a stray contact method should be persisted."""
        other = self._client("Beta Ltd")
        ClientContactMethod.objects.create(
            client=other,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 555 5555",
        )
        client = self._client("Acme Ltd")

        response = self.client.patch(
            self._update_url(client.id),
            {"phone": "09 555 5555", "name": "Acme Renamed"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.json()["error"].lower())
        client.refresh_from_db()
        self.assertEqual(client.name, "Acme Ltd")
        self.assertEqual(client.contact_methods.count(), 0)

    def test_get_client_detail_returns_primary_phone(self) -> None:
        client = self._client()
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )

        response = self.client.get(f"/api/clients/{client.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "09 111 1111")

    def test_get_client_detail_returns_empty_string_without_phone(self) -> None:
        client = self._client("Phoneless Ltd")

        response = self.client.get(f"/api/clients/{client.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phone"], "")

    def test_xero_synced_update_applies_phone_before_provider_push(self) -> None:
        client = self._client()
        client.xero_contact_id = "xero-contact-id"
        client.save()
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.update_contact.return_value = ContactResult(
            success=True, external_id=client.xero_contact_id, name=client.name
        )

        with patch(
            "apps.client.services.client_rest_service.get_provider",
            return_value=provider,
        ):
            with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.patch(
                        self._update_url(client.id),
                        {"phone": "09 444 4444"},
                        format="json",
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client"]["phone"], "09 444 4444")
        pushed_client = provider.update_contact.call_args.args[0]
        pushed_contact = pushed_client.get_client_for_xero()
        self.assertEqual(pushed_contact.phones[0].phone_number, "09 444 4444")
        rematch.assert_called_once_with(
            [ClientContactMethod.normalize_phone("09 444 4444")]
        )

    def test_xero_synced_blank_phone_clears_before_provider_push(self) -> None:
        client = self._client()
        client.xero_contact_id = "xero-contact-id"
        client.save()
        ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 111 1111",
            is_primary=True,
        )
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.update_contact.return_value = ContactResult(
            success=True, external_id=client.xero_contact_id, name=client.name
        )

        with patch(
            "apps.client.services.client_rest_service.get_provider",
            return_value=provider,
        ):
            with patch(
                "apps.client.services.client_rest_service."
                "rematch_phone_calls_task.delay"
            ) as rematch:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.patch(
                        self._update_url(client.id),
                        {"phone": ""},
                        format="json",
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client"]["phone"], "")
        pushed_client = provider.update_contact.call_args.args[0]
        pushed_contact = pushed_client.get_client_for_xero()
        self.assertIsNone(pushed_contact.phones[0].phone_number)
        rematch.assert_called_once_with(
            [ClientContactMethod.normalize_phone("09 111 1111")]
        )

    def test_phone_rematch_waits_until_transaction_commit(self) -> None:
        client = self._client()

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                response = self.client.patch(
                    self._update_url(client.id),
                    {"phone": "09 111 1111"},
                    format="json",
                )
                rematch.assert_not_called()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(callbacks), 1)
            rematch.assert_not_called()
            callbacks[0]()
            rematch.assert_called_once_with(
                [ClientContactMethod.normalize_phone("09 111 1111")]
            )


class ClientCreatePhoneTests(BaseTestCase):
    """Guards the phone entry restored on the create-client modal."""

    def _provider(self) -> MagicMock:
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.search_contact_by_name.return_value = None
        provider.create_contact.return_value = ContactResult(
            success=True, external_id="xero-contact-id", name="New Client"
        )
        return provider

    def _create(self, provider: MagicMock, **payload: str) -> Client:
        from apps.client.services.client_rest_service import ClientRestService

        data: dict[str, str] = {"name": "New Client", "email": "", "address": ""}
        data.update(payload)
        with patch(
            "apps.client.services.client_rest_service.get_provider",
            return_value=provider,
        ):
            return ClientRestService.create_client(data)

    def test_create_with_phone_creates_primary_client_method(self) -> None:
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                client = self._create(self._provider(), phone="09 777 7777")

        method = ClientContactMethod.objects.get(client=client)
        self.assertEqual(method.method_type, ClientContactMethod.MethodType.PHONE)
        self.assertEqual(method.value, "09 777 7777")
        self.assertTrue(method.is_primary)

    def test_create_without_phone_creates_no_methods(self) -> None:
        client = self._create(self._provider())

        self.assertEqual(ClientContactMethod.objects.filter(client=client).count(), 0)

    def test_create_with_conflicting_phone_rolls_back_client(self) -> None:
        from apps.workflow.exceptions import AlreadyLoggedException

        owner = Client.objects.create(
            name="Owner Ltd", xero_last_modified=timezone.now()
        )
        ClientContactMethod.objects.create(
            client=owner,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 777 7777",
        )
        provider = self._provider()

        with self.assertRaises(AlreadyLoggedException) as ctx:
            self._create(provider, phone="09 777 7777")

        self.assertIn("already belongs", str(ctx.exception))
        self.assertFalse(Client.objects.filter(name="New Client").exists())
        provider.create_contact.assert_not_called()


class ClientContactMethodApiTests(BaseAPITestCase):
    def _client(self, name: str = "Acme Ltd") -> Client:
        return Client.objects.create(name=name, xero_last_modified=timezone.now())

    def test_list_paginates_phone_contact_methods(self) -> None:
        """Catches CRM calls page regressions that fetch every phone method."""
        self.client.force_authenticate(user=self.test_staff)
        client = self._client("Acme Ltd")
        for index in range(3):
            ClientContactMethod.objects.create(
                client=client,
                method_type=ClientContactMethod.MethodType.PHONE,
                value=f"021 555 10{index}",
            )

        response = self.client.get(
            "/api/clients/contact-methods/",
            {"method_type": "phone", "page_size": "2"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["page_size"], 2)
        self.assertEqual(payload["total_pages"], 2)
        self.assertEqual(len(payload["results"]), 2)

    def test_list_page_size_is_capped(self) -> None:
        """Catches accidental oversized contact-method responses."""
        self.client.force_authenticate(user=self.test_staff)
        client = self._client("Acme Ltd")
        for index in range(101):
            ClientContactMethod.objects.create(
                client=client,
                method_type=ClientContactMethod.MethodType.PHONE,
                value=f"021 555 {index:03d}",
            )

        response = self.client.get(
            "/api/clients/contact-methods/",
            {"method_type": "phone", "page_size": "250"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 101)
        self.assertEqual(payload["page_size"], 100)
        self.assertEqual(len(payload["results"]), 100)

    def test_updating_phone_contact_method_rematches_affected_calls(self) -> None:
        """Catches stale call ownership after a customer phone number changes."""
        self.client.force_authenticate(user=self.test_staff)
        client = self._client("Acme Ltd")
        method = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 100",
        )
        old_call = self._call("old-number", origin="021 555 100", client=client)
        new_call = self._call("new-number", origin="021 555 200", client=None)

        with patch(
            "apps.client.views.client_contact_method_viewset."
            "rematch_phone_calls_task.delay",
            side_effect=rematch_calls_for_numbers,
        ) as rematch:
            response = self.client.patch(
                f"/api/clients/contact-methods/{method.id}/",
                {"value": "021 555 200"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        rematch.assert_called_once_with(["+6421555100", "+6421555200"])
        old_call.refresh_from_db()
        new_call.refresh_from_db()
        self.assertIsNone(old_call.client)
        self.assertEqual(new_call.client, client)

    def test_deleting_phone_contact_method_unmatches_affected_calls(self) -> None:
        """Catches deleted phone numbers continuing to own CRM calls."""
        self.client.force_authenticate(user=self.test_staff)
        client = self._client("Acme Ltd")
        method = ClientContactMethod.objects.create(
            client=client,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 100",
        )
        call = self._call("deleted-number", origin="021 555 100", client=client)

        with patch(
            "apps.client.views.client_contact_method_viewset."
            "rematch_phone_calls_task.delay",
            side_effect=rematch_calls_for_numbers,
        ) as rematch:
            response = self.client.delete(f"/api/clients/contact-methods/{method.id}/")

        self.assertEqual(response.status_code, 204)
        rematch.assert_called_once_with(["+6421555100"])
        call.refresh_from_db()
        self.assertIsNone(call.client)

    def _call(
        self,
        provider_id: str,
        *,
        origin: str,
        client: Client | None,
    ) -> PhoneCallRecord:
        call_datetime = timezone.now()
        return PhoneCallRecord.objects.create(
            provider_call_id=f"account:{provider_id}",
            account_code="account",
            call_datetime=call_datetime,
            call_date=timezone.localdate(),
            call_time=call_datetime.time(),
            origin=origin,
            destination="+6496365131",
            client=client,
            raw_json={
                "id": provider_id,
                "calldate": timezone.localdate().isoformat(),
                "calltime": call_datetime.time().isoformat(timespec="seconds"),
            },
        )
