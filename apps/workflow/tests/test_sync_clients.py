"""Tests for sync_clients handling of archived Xero contacts."""

from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.client.models import Client, ClientContactMethod
from apps.crm.models import PhoneCallRecord
from apps.crm.services.phone_call_service import rematch_calls_for_numbers
from apps.workflow.api.xero.reprocess_xero import (
    _xero_phone_value,
    set_client_fields,
    sync_xero_phone_methods,
)
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import AppError


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


class XeroPhoneMethodSyncTests(TestCase):
    def _client_with_phone(
        self,
        name: str,
        number: str = "021 555 123",
        phone_type: str = "DEFAULT",
    ) -> Client:
        return Client.objects.create(
            name=name,
            xero_last_modified=timezone.now(),
            raw_json={
                "_phones": [
                    {
                        "_phone_type": phone_type,
                        "_phone_number": number,
                        "_phone_area_code": "",
                        "_phone_country_code": "",
                    }
                ]
            },
        )

    def test_duplicate_phone_owner_crashes_sync_and_persists_app_error(self) -> None:
        existing = Client.objects.create(
            name="Existing Phone Owner",
            xero_last_modified=timezone.now(),
        )
        imported = self._client_with_phone("Imported Phone Owner")
        ClientContactMethod.objects.create(
            client=existing,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        before = AppError.objects.count()

        with self.assertRaisesRegex(
            AlreadyLoggedException,
            "already belongs to.*Existing Phone Owner",
        ):
            sync_xero_phone_methods(imported)

        self.assertEqual(AppError.objects.count(), before + 1)
        app_error = AppError.objects.order_by("-timestamp").first()
        assert app_error is not None
        # The persisted message must name the syncing client, the number, and
        # the conflicting owner so the operator can fix the data.
        self.assertIn("Imported Phone Owner", app_error.message)
        self.assertIn("+6421555123", app_error.message)
        self.assertIn("Existing Phone Owner", app_error.message)

    def test_resync_of_existing_number_is_grandfathered(self) -> None:
        """Re-syncing a client's own already-stored number must not raise."""
        owner = self._client_with_phone("Phone Owner")
        # A cross-client legacy row exists for the same number (grandfathered),
        # inserted bypassing the guard as pre-guard data was.
        other = Client.objects.create(
            name="Legacy Other Owner", xero_last_modified=timezone.now()
        )
        legacy = ClientContactMethod(
            client=other,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        legacy.normalized_value = ClientContactMethod.normalize_phone("021 555 123")
        ClientContactMethod.objects.bulk_create([legacy])
        # owner already stores the number too (its own row).
        owner_method = ClientContactMethod(
            client=owner,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        owner_method.normalized_value = ClientContactMethod.normalize_phone(
            "021 555 123"
        )
        ClientContactMethod.objects.bulk_create([owner_method])

        created = sync_xero_phone_methods(owner)  # must not raise

        self.assertEqual(created, [])
        owner_method.refresh_from_db()
        # Xero owns the number's existence only; the existing row is untouched.
        self.assertEqual(owner_method.label, "")

    def test_user_edited_label_and_primary_survive_resync(self) -> None:
        owner = self._client_with_phone("Phone Owner")
        created = sync_xero_phone_methods(owner)
        self.assertEqual(created, ["+6421555123"])
        imported_method = ClientContactMethod.objects.get(client=owner)
        self.assertEqual(imported_method.label, "DEFAULT")
        self.assertTrue(imported_method.is_primary)

        # CRM user relabels the imported number and picks a LOCAL primary.
        imported_method.label = "Reception"
        imported_method.save()
        local_primary = ClientContactMethod.objects.create(
            client=owner,
            method_type=ClientContactMethod.MethodType.PHONE,
            value="09 555 000",
            label="After hours",
            is_primary=True,
            source=ClientContactMethod.Source.LOCAL,
        )

        self.assertEqual(sync_xero_phone_methods(owner), [])

        imported_method.refresh_from_db()
        local_primary.refresh_from_db()
        self.assertEqual(imported_method.label, "Reception")
        self.assertFalse(imported_method.is_primary)
        self.assertTrue(local_primary.is_primary)
        self.assertEqual(imported_method.source, ClientContactMethod.Source.IMPORTED)

    def test_unchanged_resync_does_not_write_the_method_row(self) -> None:
        owner = self._client_with_phone("Phone Owner")
        sync_xero_phone_methods(owner)
        method = ClientContactMethod.objects.get(client=owner)
        updated_at_before = method.updated_at

        with CaptureQueriesContext(connection) as ctx:
            sync_xero_phone_methods(owner)

        writes = [
            query["sql"]
            for query in ctx.captured_queries
            if not query["sql"].startswith("SELECT")
        ]
        self.assertEqual(writes, [])
        method.refresh_from_db()
        self.assertEqual(method.updated_at, updated_at_before)

    def test_new_xero_number_dispatches_rematch_of_historical_calls(self) -> None:
        """Numbers imported from Xero must attach existing calls, like UI edits."""
        client = self._client_with_phone("Rematch Client")
        call_datetime = timezone.now()
        call = PhoneCallRecord.objects.create(
            provider_call_id="account:xero-rematch",
            account_code="account",
            call_datetime=call_datetime,
            call_date=timezone.localdate(),
            call_time=call_datetime.time(),
            origin="+6421555123",
            destination="+6490000000",
            raw_json={"id": "xero-rematch"},
        )

        with patch(
            "apps.workflow.api.xero.reprocess_xero.rematch_phone_calls_task.delay",
            side_effect=rematch_calls_for_numbers,
        ) as rematch:
            with self.captureOnCommitCallbacks(execute=True):
                set_client_fields(client)

        rematch.assert_called_once_with(["+6421555123"])
        call.refresh_from_db()
        self.assertEqual(call.client, client)

        # An unchanged re-sync creates nothing and must not dispatch a rematch.
        with self.captureOnCommitCallbacks() as callbacks:
            set_client_fields(client)
        self.assertEqual(callbacks, [])


class XeroPhoneValueTests(TestCase):
    def test_explicit_null_fields_do_not_leak_the_string_none(self) -> None:
        # Xero JSON often carries explicit nulls for unset optional parts. dict
        # .get(key, "") would return None for those, so the f-string embedded
        # the literal "None" into the stored value; the value must stay clean.
        value = _xero_phone_value(
            {
                "_phone_number": "5551234",
                "_phone_area_code": None,
                "_phone_country_code": None,
            }
        )

        self.assertEqual(value, "5551234")
        self.assertNotIn("None", value)
