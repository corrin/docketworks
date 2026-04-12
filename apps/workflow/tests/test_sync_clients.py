"""Tests for sync_clients handling of archived Xero contacts."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.client.models import Client


def _make_raw_json(contact_id, name, status="ACTIVE", merged_to=None):
    """Return raw_json shaped like real Xero contact data stored in the DB.

    Based on actual production records — includes the full set of underscore-
    prefixed fields that process_xero_data() produces from the SDK objects.
    """
    return {
        "_contact_id": contact_id,
        "_merged_to_contact_id": merged_to,
        "_contact_number": None,
        "_account_number": None,
        "_contact_status": status,
        "_name": name,
        "_first_name": None,
        "_last_name": None,
        "_company_number": None,
        "_email_address": "",
        "_contact_persons": [],
        "_bank_account_details": "",
        "_tax_number": None,
        "_tax_number_type": None,
        "_accounts_receivable_tax_type": None,
        "_accounts_payable_tax_type": None,
        "_addresses": [
            {
                "_address_type": "STREET",
                "_address_line1": None,
                "_address_line2": None,
                "_address_line3": None,
                "_address_line4": None,
                "_city": "",
                "_region": "",
                "_postal_code": "",
                "_country": "",
                "_attention_to": None,
                "discriminator": None,
            },
            {
                "_address_type": "POBOX",
                "_address_line1": None,
                "_address_line2": None,
                "_address_line3": None,
                "_address_line4": None,
                "_city": "",
                "_region": "",
                "_postal_code": "",
                "_country": "",
                "_attention_to": None,
                "discriminator": None,
            },
        ],
        "_phones": [
            {
                "_phone_type": "DDI",
                "_phone_number": "",
                "_phone_area_code": "",
                "_phone_country_code": "",
                "discriminator": None,
            },
            {
                "_phone_type": "DEFAULT",
                "_phone_number": "",
                "_phone_area_code": "",
                "_phone_country_code": "",
                "discriminator": None,
            },
            {
                "_phone_type": "FAX",
                "_phone_number": "",
                "_phone_area_code": "",
                "_phone_country_code": "",
                "discriminator": None,
            },
            {
                "_phone_type": "MOBILE",
                "_phone_number": "",
                "_phone_area_code": "",
                "_phone_country_code": "",
                "discriminator": None,
            },
        ],
        "_is_supplier": False,
        "_is_customer": False,
        "_sales_default_line_amount_type": None,
        "_purchases_default_line_amount_type": None,
        "_default_currency": None,
        "_xero_network_key": None,
        "_sales_default_account_code": None,
        "_purchases_default_account_code": None,
        "_sales_tracking_categories": None,
        "_purchases_tracking_categories": None,
        "_tracking_category_name": None,
        "_tracking_category_option": None,
        "_payment_terms": None,
        "_updated_date_utc": "2026-02-14T23:49:10.183000+00:00",
        "_contact_groups": [],
        "_website": None,
        "_branding_theme": None,
        "_batch_payments": None,
        "_discount": None,
        "_balances": None,
        "_attachments": None,
        "_has_attachments": False,
        "_validation_errors": None,
        "_has_validation_errors": False,
        "_status_attribute_string": None,
        "discriminator": None,
    }


def _make_xero_contact(contact_id, name, status="ACTIVE", merged_to=None):
    """Build a fake Xero SDK contact object.

    The real xero_python Contact has many attributes, but sync_clients()
    only accesses contact_id, contact_status, and merged_to_contact_id.
    """
    contact = SimpleNamespace(
        contact_id=contact_id,
        contact_status=status,
    )
    if merged_to is not None:
        contact.merged_to_contact_id = merged_to
    return contact


class SyncClientsArchivedContactTests(TestCase):
    """Regression tests for archived-contact name collisions during Xero sync.

    Reproduces the production scenario where Xero merges two contacts:
    the surviving contact stays ACTIVE, the old one becomes ARCHIVED with
    the same name.  sync_clients must handle both without crashing.
    """

    def setUp(self):
        self.active_xero_id = "9568adbc-aaaa-bbbb-cccc-000000000001"
        self.archived_xero_id = "17aa5e1e-aaaa-bbbb-cccc-000000000002"
        self.client_name = "Powder Coating Group NZ Limited"

        # Pre-existing client linked to the active Xero contact
        self.existing_client = Client.objects.create(
            name=self.client_name,
            xero_contact_id=self.active_xero_id,
            xero_last_modified=timezone.now(),
        )

    def _mock_process_xero_data(self, contact):
        """Substitute for process_xero_data that returns realistic raw_json."""
        return _make_raw_json(
            contact_id=contact.contact_id,
            name=self.client_name,
            status=contact.contact_status,
            merged_to=getattr(contact, "merged_to_contact_id", None),
        )

    @patch("apps.workflow.api.xero.transforms.set_client_fields")
    @patch("apps.workflow.api.xero.transforms.process_xero_data")
    def test_archived_contact_creates_separate_record(
        self, mock_process, mock_set_fields
    ):
        """An archived Xero contact with a duplicate name should create a
        separate client record instead of raising ValueError."""
        mock_process.side_effect = self._mock_process_xero_data

        archived_contact = _make_xero_contact(
            self.archived_xero_id,
            self.client_name,
            status="ARCHIVED",
            merged_to=self.active_xero_id,
        )

        from apps.workflow.api.xero.sync import sync_clients

        result = sync_clients([archived_contact])

        self.assertEqual(len(result), 1)
        new_client = result[0]

        # Must be a different DB record from the existing one
        self.assertNotEqual(new_client.id, self.existing_client.id)
        self.assertEqual(new_client.xero_contact_id, self.archived_xero_id)
        self.assertTrue(new_client.xero_archived)
        self.assertEqual(new_client.xero_merged_into_id, self.active_xero_id)

        # Original client unchanged
        self.existing_client.refresh_from_db()
        self.assertEqual(self.existing_client.xero_contact_id, self.active_xero_id)
        self.assertFalse(self.existing_client.xero_archived)

    @patch("apps.workflow.api.xero.transforms.set_client_fields")
    @patch("apps.workflow.api.xero.transforms.process_xero_data")
    def test_active_contact_name_collision_still_raises(
        self, mock_process, mock_set_fields
    ):
        """An active Xero contact whose name collides with an existing client
        linked to a different Xero ID should still raise ValueError."""
        mock_process.side_effect = self._mock_process_xero_data

        conflicting_contact = _make_xero_contact(
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            self.client_name,
            status="ACTIVE",
        )

        from apps.workflow.api.xero.sync import sync_clients

        with self.assertRaises(ValueError) as ctx:
            sync_clients([conflicting_contact])

        self.assertIn(self.active_xero_id, str(ctx.exception))

    @patch("apps.workflow.api.xero.transforms.set_client_fields")
    @patch("apps.workflow.api.xero.transforms.process_xero_data")
    def test_archived_contact_with_existing_xero_id_updates_in_place(
        self, mock_process, mock_set_fields
    ):
        """If the archived contact's xero_contact_id already exists in the DB,
        it should update that record (the normal 'already linked' path)."""
        mock_process.side_effect = self._mock_process_xero_data

        # Contact whose ID matches the existing client — just now archived
        same_id_contact = _make_xero_contact(
            self.active_xero_id,
            self.client_name,
            status="ARCHIVED",
        )

        from apps.workflow.api.xero.sync import sync_clients

        result = sync_clients([same_id_contact])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, self.existing_client.id)

        self.existing_client.refresh_from_db()
        self.assertTrue(self.existing_client.xero_archived)
