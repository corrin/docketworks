from django.test import TestCase
from django.utils import timezone

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.testing import BaseAPITestCase


class ClientContactMethodTests(TestCase):
    def _client(self, name="Acme Ltd"):
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


class ClientContactMethodApiTests(BaseAPITestCase):
    def _client(self, name: str = "Acme Ltd") -> Client:
        return Client.objects.create(name=name, xero_last_modified=timezone.now())

    def test_list_limit_bounds_phone_contact_methods(self) -> None:
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
            {"method_type": "phone", "limit": "2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_list_limit_rejects_unbounded_values(self) -> None:
        """Catches accidental oversized contact-method responses."""
        self.client.force_authenticate(user=self.test_staff)

        response = self.client.get(
            "/api/clients/contact-methods/",
            {"method_type": "phone", "limit": "250"},
        )

        self.assertEqual(response.status_code, 400)
