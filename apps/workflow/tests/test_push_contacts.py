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

from apps.company.models import ClientContactMethod, Company
from apps.workflow.tests.fixtures.xero_responses import make_create_contacts_response


def _make_client(**overrides):
    defaults = {
        "name": "Acme Ltd",
        "email": "info@acme.test",
        "address": "123 Test Street",
        "xero_last_modified": timezone.now(),
    }
    phone = overrides.pop("phone", None)
    defaults.update(overrides)
    company = Company.objects.create(**defaults)
    if phone is not None:
        ClientContactMethod.objects.create(
            company=company,
            method_type=ClientContactMethod.MethodType.PHONE,
            value=phone,
            is_primary=True,
        )
    return company


def _create_response(contact_id, name):
    """Mirror what AccountingApi.create_contacts / update_contact returns:
    a Contacts wrapper holding a list of Contact SDK instances."""
    return Contacts(contacts=[Contact(contact_id=contact_id, name=name)])


@patch("time.sleep")
@patch("apps.workflow.api.xero.push.get_tenant_id", return_value="tenant-1")
@patch("apps.workflow.api.xero.push.AccountingApi")
class SyncClientToXeroPushTests(TestCase):
    """sync_company_to_xero — both branches must pass Contact instances."""

    def test_new_client_calls_create_contacts_with_sdk_contact(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        company = _make_client(phone="027 351 8326")
        mock_api = mock_api_class.return_value
        mock_api.create_contacts.return_value = _create_response(
            "00000000-0000-0000-0000-000000000001", company.name
        )

        from apps.workflow.api.xero.push import sync_company_to_xero

        result = sync_company_to_xero(company)

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
        company = _make_client(xero_contact_id=xero_id, phone="027 351 8327")
        mock_api = mock_api_class.return_value
        mock_api.update_contact.return_value = _create_response(xero_id, company.name)

        from apps.workflow.api.xero.push import sync_company_to_xero

        result = sync_company_to_xero(company)

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
    """create_company_contact_in_xero — passes Contact, saves xero_contact_id."""

    def test_passes_sdk_contact_and_saves_id(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        company = _make_client(phone="027 351 8328")
        new_id = "00000000-0000-0000-0000-000000000042"
        mock_api = mock_api_class.return_value
        # Use the captured-from-Xero response fixture so the mock matches the
        # real shape (contact_status, updated_date_utc, etc.); only override
        # the fields this test actually asserts on.
        mock_api.create_contacts.return_value = make_create_contacts_response(
            contact_id=new_id, name=company.name
        )

        from apps.workflow.api.xero.push import create_company_contact_in_xero

        result = create_company_contact_in_xero(company)

        self.assertEqual(result, new_id)
        contact = mock_api.create_contacts.call_args.kwargs["contacts"]["contacts"][0]
        self.assertIsInstance(contact, Contact)
        company.refresh_from_db()
        self.assertEqual(company.xero_contact_id, new_id)


@patch("time.sleep")
@patch("apps.workflow.api.xero.push.get_tenant_id", return_value="tenant-1")
@patch("apps.workflow.api.xero.push.AccountingApi")
class BulkCreateContactsInXeroTests(TestCase):
    """bulk_create_contacts_in_xero — Contact instances throughout."""

    def test_passes_list_of_sdk_contacts(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        clients = [
            _make_client(name=f"Bulk Company {i}", phone=f"027 351 84{i:02d}")
            for i in range(3)
        ]
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
        company = _make_client(phone="027 351 8329")
        mock_api = mock_api_class.return_value
        mock_api.create_contacts.return_value = _create_response("id-1", company.name)

        from apps.workflow.api.xero.push import bulk_create_contacts_in_xero

        bulk_create_contacts_in_xero([company])

        captured = mock_api.create_contacts.call_args.kwargs["contacts"]["contacts"][0]
        self.assertIsInstance(captured, Contact)
        self.assertNotIsInstance(captured, dict)

    def test_batches_at_size_boundary(self, mock_api_class, _mock_tenant, _mock_sleep):
        clients = [
            _make_client(name=f"Boundary {i}", phone=f"027 352 {i:04d}")
            for i in range(53)
        ]
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

    def test_duplicate_names_get_distinct_ids_when_response_in_order(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        """Regression: two clients with identical names in one batch must each
        receive their own xero_contact_id. The previous name-keyed mapping
        silently overwrote the first company's mapping with the second's."""
        client_a = _make_client(
            name="Same Name",
            email="a@example.test",
            phone="027 353 0001",
        )
        client_b = _make_client(
            name="Same Name",
            email="b@example.test",
            phone="027 353 0002",
        )
        mock_api = mock_api_class.return_value
        mock_api.create_contacts.return_value = Contacts(
            contacts=[
                Contact(contact_id="id-a", name="Same Name"),
                Contact(contact_id="id-b", name="Same Name"),
            ]
        )

        from apps.workflow.api.xero.push import bulk_create_contacts_in_xero

        total = bulk_create_contacts_in_xero([client_a, client_b])

        self.assertEqual(total, 2)
        client_a.refresh_from_db()
        client_b.refresh_from_db()
        self.assertEqual(client_a.xero_contact_id, "id-a")
        self.assertEqual(client_b.xero_contact_id, "id-b")

    def test_response_out_of_order_raises_value_error(
        self, mock_api_class, _mock_tenant, _mock_sleep
    ):
        """If Xero ever stops preserving submission order, the runtime
        name-mismatch check must fail loudly rather than silently writing
        the wrong xero_contact_id."""
        client_a = _make_client(name="Alpha", phone="027 353 0003")
        client_b = _make_client(name="Beta", phone="027 353 0004")
        mock_api = mock_api_class.return_value
        mock_api.create_contacts.return_value = Contacts(
            contacts=[
                Contact(contact_id="id-b", name="Beta"),
                Contact(contact_id="id-a", name="Alpha"),
            ]
        )

        from apps.workflow.api.xero.push import bulk_create_contacts_in_xero

        with self.assertRaises(ValueError) as cm:
            bulk_create_contacts_in_xero([client_a, client_b])
        self.assertIn("response order mismatch", str(cm.exception))
