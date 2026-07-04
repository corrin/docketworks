from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.crm.models import PhoneCallRecord
from apps.testing import BaseAPITestCase


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
        old_call = self._call("old-number", origin="+6421555100", client=client)
        new_call = self._call("new-number", origin="+6421555200", client=None)

        response = self.client.patch(
            f"/api/clients/contact-methods/{method.id}/",
            {"value": "021 555 200"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
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
        call = self._call("deleted-number", origin="+6421555100", client=client)

        response = self.client.delete(f"/api/clients/contact-methods/{method.id}/")

        self.assertEqual(response.status_code, 204)
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
