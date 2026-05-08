"""Tests for outbound Xero contact push paths.

Regression coverage for Trello #305 — the dict-based payload was passed
verbatim to accounting_api.create_contacts / update_contact, and Xero
silently dropped every field except Name on the wire. After the fix, all
three push paths must pass xero_python.accounting.models.Contact instances.

There is no prior test coverage for these functions; this is the first.
"""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from xero_python.accounting.models import Contact, Contacts

from apps.client.models import Client
from apps.workflow.tests.fixtures.xero_responses import make_create_contacts_response


def _make_client(**overrides):
    defaults = {
        "name": "Acme Ltd",
        "email": "info@acme.test",
        "phone": "027 351 8326",
        "address": "123 Test Street",
        "xero_last_modified": timezone.now(),
    }
    defaults.update(overrides)
    return Client.objects.create(**defaults)


def _create_response(contact_id, name):
    """Mirror what AccountingApi.create_contacts / update_contact returns:
    a Contacts wrapper holding a list of Contact SDK instances."""
    return Contacts(contacts=[Contact(contact_id=contact_id, name=name)])


@patch("time.sleep")
@patch("apps.workflow.api.xero.push.get_tenant_id", return_value="tenant-1")
@patch("apps.workflow.api.xero.push.AccountingApi")
class SyncClientToXeroPushTests(TestCase):
    """sync_client_to_xero — both branches must pass Contact instances."""

    def test_new_client_calls_create_contacts_with_sdk_contact(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        client = _make_client()
        mock_api = mock_api_class.return_value
        mock_api.create_contacts.return_value = _create_response(
            "00000000-0000-0000-0000-000000000001", client.name
        )

        from apps.workflow.api.xero.push import sync_client_to_xero

        result = sync_client_to_xero(client)

        self.assertTrue(result)
        mock_api.create_contacts.assert_called_once()
        kwargs = mock_api.create_contacts.call_args.kwargs
        contact = kwargs["contacts"]["contacts"][0]
        self.assertIsInstance(contact, Contact)
        self.assertEqual(contact.email_address, "info@acme.test")
        self.assertEqual(contact.phones[0].phone_number, "027 351 8326")

    def test_existing_client_calls_update_contact_with_sdk_contact(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        xero_id = "9568adbc-aaaa-bbbb-cccc-000000000001"
        client = _make_client(xero_contact_id=xero_id)
        mock_api = mock_api_class.return_value
        mock_api.update_contact.return_value = _create_response(xero_id, client.name)

        from apps.workflow.api.xero.push import sync_client_to_xero

        result = sync_client_to_xero(client)

        self.assertTrue(result)
        mock_api.update_contact.assert_called_once()
        kwargs = mock_api.update_contact.call_args.kwargs
        contact = kwargs["contacts"]["contacts"][0]
        self.assertIsInstance(contact, Contact)
        # contact_id must come from the SDK model itself, not a caller-side
        # dict mutation (regression for push.py:40 `contact_data["ContactID"] = ...`).
        self.assertEqual(contact.contact_id, xero_id)


@patch("time.sleep")
@patch("apps.workflow.api.xero.push.get_tenant_id", return_value="tenant-1")
@patch("apps.workflow.api.xero.push.AccountingApi")
class CreateClientContactInXeroTests(TestCase):
    """create_client_contact_in_xero — passes Contact, saves xero_contact_id."""

    def test_passes_sdk_contact_and_saves_id(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        client = _make_client()
        new_id = "00000000-0000-0000-0000-000000000042"
        mock_api = mock_api_class.return_value
        # Use the captured-from-Xero response fixture so the mock matches the
        # real shape (contact_status, updated_date_utc, etc.); only override
        # the fields this test actually asserts on.
        mock_api.create_contacts.return_value = make_create_contacts_response(
            contact_id=new_id, name=client.name
        )

        from apps.workflow.api.xero.push import create_client_contact_in_xero

        result = create_client_contact_in_xero(client)

        self.assertEqual(result, new_id)
        contact = mock_api.create_contacts.call_args.kwargs["contacts"]["contacts"][0]
        self.assertIsInstance(contact, Contact)
        client.refresh_from_db()
        self.assertEqual(client.xero_contact_id, new_id)


@patch("time.sleep")
@patch("apps.workflow.api.xero.push.get_tenant_id", return_value="tenant-1")
@patch("apps.workflow.api.xero.push.AccountingApi")
class BulkCreateContactsInXeroTests(TestCase):
    """bulk_create_contacts_in_xero — Contact instances throughout."""

    def test_passes_list_of_sdk_contacts(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        clients = [_make_client(name=f"Bulk Client {i}") for i in range(3)]
        mock_api = mock_api_class.return_value
        mock_api.create_contacts.return_value = Contacts(
            contacts=[
                Contact(contact_id=f"id-{i}", name=clients[i].name) for i in range(3)
            ]
        )

        from apps.workflow.api.xero.push import bulk_create_contacts_in_xero

        total = bulk_create_contacts_in_xero(clients)

        self.assertEqual(total, 3)
        sent = mock_api.create_contacts.call_args.kwargs["contacts"]["contacts"]
        self.assertEqual(len(sent), 3)
        for contact in sent:
            self.assertIsInstance(contact, Contact)

    def test_no_name_dict_key_workaround_in_payload(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        """Tombstone for the deleted name->Name dict mutation at push.py:521-524.

        Anyone re-introducing the dict path "for safety" trips this immediately.
        """
        client = _make_client()
        mock_api = mock_api_class.return_value
        mock_api.create_contacts.return_value = _create_response("id-1", client.name)

        from apps.workflow.api.xero.push import bulk_create_contacts_in_xero

        bulk_create_contacts_in_xero([client])

        captured = mock_api.create_contacts.call_args.kwargs["contacts"]["contacts"][0]
        self.assertIsInstance(captured, Contact)
        self.assertNotIsInstance(captured, dict)

    def test_batches_at_size_boundary(self, mock_api_class, _mock_tenant, _mock_sleep):
        clients = [_make_client(name=f"Boundary {i}") for i in range(53)]
        mock_api = mock_api_class.return_value

        def respond(*args, **kwargs):
            sent = kwargs["contacts"]["contacts"]
            return Contacts(
                contacts=[Contact(contact_id=f"id-{c.name}", name=c.name) for c in sent]
            )

        mock_api.create_contacts.side_effect = respond

        from apps.workflow.api.xero.push import bulk_create_contacts_in_xero

        total = bulk_create_contacts_in_xero(clients, batch_size=50)

        self.assertEqual(mock_api.create_contacts.call_count, 2)
        self.assertEqual(total, 53)
