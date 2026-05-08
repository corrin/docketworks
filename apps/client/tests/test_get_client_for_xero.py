"""Tests for Client.get_client_for_xero().

Regression coverage for Trello #305 — the snake_case dict that this method
used to return caused Xero to silently drop every field except Name on the
wire. The fix is to return a xero_python.accounting.models.Contact SDK
instance (with Phone and Address instances inside), which the SDK's
attribute_map translates to PascalCase correctly.
"""

from django.test import TestCase
from django.utils import timezone
from xero_python.accounting.models import Address, Contact, Phone
from xero_python.api_client.serializer import serialize

from apps.client.models import Client


class GetClientForXeroTests(TestCase):
    """Pin the wire-format contract independent of which push function consumes it."""

    def _make_client(self, **overrides):
        defaults = {
            "name": "Acme Ltd",
            "xero_last_modified": timezone.now(),
        }
        defaults.update(overrides)
        return Client.objects.create(**defaults)

    def test_returns_sdk_contact_instance(self):
        """The payload must be a xero_python Contact, not a dict.

        If anyone reverts to a snake_case dict, this fails. The SDK's
        attribute_map only translates fields for model instances; raw dicts
        ship verbatim and Xero drops every non-Name field.
        """
        client = self._make_client()

        payload = client.get_client_for_xero()

        self.assertIsInstance(payload, Contact)

    def test_phones_are_sdk_phone_instances(self):
        client = self._make_client(phone="027 351 8326")

        payload = client.get_client_for_xero()

        self.assertIsInstance(payload.phones[0], Phone)

    def test_addresses_are_sdk_address_instances(self):
        client = self._make_client(address="123 Test Street")

        payload = client.get_client_for_xero()

        self.assertIsInstance(payload.addresses[0], Address)

    def test_populated_client_carries_all_fields(self):
        """Every field a fully-populated Client supplies must reach the Contact."""
        client = self._make_client(
            email="info@acme.test",
            phone="027 351 8326",
            address="123 Test Street",
            is_account_customer=True,
        )

        payload = client.get_client_for_xero()

        self.assertEqual(payload.name, "Acme Ltd")
        self.assertEqual(payload.email_address, "info@acme.test")
        self.assertTrue(payload.is_customer)
        self.assertEqual(payload.phones[0].phone_type, "DEFAULT")
        self.assertEqual(payload.phones[0].phone_number, "027 351 8326")
        self.assertEqual(payload.addresses[0].address_type, "STREET")
        self.assertEqual(payload.addresses[0].address_line1, "123 Test Street")
        self.assertEqual(payload.addresses[0].attention_to, "Acme Ltd")

    def test_existing_client_populates_contact_id_on_instance(self):
        """contact_id lives on the Contact, not as a caller-side dict mutation.

        Regression for the dict-mutation pattern at push.py:40
        (`contact_data["ContactID"] = client.xero_contact_id`).
        """
        xero_id = "9568adbc-aaaa-bbbb-cccc-000000000001"
        client = self._make_client(xero_contact_id=xero_id)

        payload = client.get_client_for_xero()

        self.assertEqual(payload.contact_id, xero_id)

    def test_no_email_emits_none_not_empty_string(self):
        """An unset email must not push an empty string to Xero.

        Empty string overwrites any operator-typed email Xero already holds
        on a round-trip update. The masked side-effect of #305.
        """
        client = self._make_client(email=None)

        payload = client.get_client_for_xero()

        self.assertIsNone(payload.email_address)

    def test_no_phone_emits_none_not_empty_string(self):
        client = self._make_client(phone=None)

        payload = client.get_client_for_xero()

        self.assertIsNone(payload.phones[0].phone_number)

    def test_no_address_emits_none_not_empty_string(self):
        client = self._make_client(address=None)

        payload = client.get_client_for_xero()

        self.assertIsNone(payload.addresses[0].address_line1)

    def test_missing_name_raises_value_error(self):
        """The name guard must still trip."""
        client = self._make_client()
        client.name = ""

        with self.assertRaises(ValueError):
            client.get_client_for_xero()

    def test_serialized_wire_format_is_pascalcase(self):
        """End-to-end wire format check — the bytes Xero would actually receive.

        The original bug shipped snake_case JSON (`name`, `email_address`, …)
        because we passed a raw dict; Xero matched only `Name` and silently
        dropped the rest. Running the payload through the SDK's serializer
        gives the exact wire format. This test pins PascalCase across all
        the fields that were silently lost so the bug cannot regress at
        any layer between the model and the HTTP body.
        """
        client = self._make_client(
            email="info@acme.test",
            phone="027 351 8326",
            address="123 Test Street",
            is_account_customer=True,
        )

        wire = serialize(client.get_client_for_xero())

        self.assertEqual(wire["Name"], "Acme Ltd")
        self.assertEqual(wire["EmailAddress"], "info@acme.test")
        self.assertTrue(wire["IsCustomer"])
        self.assertEqual(wire["Phones"][0]["PhoneType"], "DEFAULT")
        self.assertEqual(wire["Phones"][0]["PhoneNumber"], "027 351 8326")
        self.assertEqual(wire["Addresses"][0]["AddressType"], "STREET")
        self.assertEqual(wire["Addresses"][0]["AddressLine1"], "123 Test Street")
        # And the broken snake_case keys must be absent.
        for forbidden in (
            "name",
            "email_address",
            "is_customer",
            "phones",
            "addresses",
        ):
            self.assertNotIn(forbidden, wire)
