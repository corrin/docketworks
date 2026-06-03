from django.test import TestCase
from django.utils import timezone

from apps.client.models import Client, ClientContact, ClientContactMethod


class ClientContactMethodTests(TestCase):
    def _client(self, name="Acme Ltd"):
        return Client.objects.create(name=name, xero_last_modified=timezone.now())

    def test_phone_normalization_matches_nz_variants(self) -> None:
        self.assertEqual(
            ClientContactMethod.normalize_phone("+64 9 636 5131"),
            "+6496365131",
        )
        self.assertEqual(
            ClientContactMethod.normalize_phone("09 636 5131"),
            "+6496365131",
        )

    def test_primary_phone_is_single_per_client_owner(self) -> None:
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
