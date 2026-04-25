from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.accounts.models import Staff
from apps.workflow.services import db_scrubber
from apps.workflow.services.db_scrubber import _scrub_staff


class ScrubSafetyGateTests(SimpleTestCase):

    def test_scrub_refuses_if_alias_name_does_not_end_in_scrub(self):
        bad = dict(settings.DATABASES)
        bad["scrub"] = dict(bad["scrub"])
        bad["scrub"]["NAME"] = "dw_yourco_prod"
        with override_settings(DATABASES=bad):
            with self.assertRaisesRegex(RuntimeError, "must end in '_scrub'"):
                db_scrubber.scrub()

    @patch("apps.workflow.services.db_scrubber._scrub_clients")
    @patch("apps.workflow.services.db_scrubber._scrub_staff")
    @patch("apps.workflow.services.db_scrubber.transaction")
    def test_scrub_runs_on_correctly_named_alias(
        self, mock_transaction, mock_scrub_staff, mock_scrub_clients
    ):
        # Smoke: correctly-named scrub DB, scrub() passes safety gate
        # and attempts to open a transaction (mocked here to avoid DB setup).
        db_scrubber.scrub()
        mock_transaction.atomic.assert_called_once_with(using="scrub")
        mock_scrub_staff.assert_called_once()
        mock_scrub_clients.assert_called_once()


class ScrubStaffTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_scrub_overwrites_only_name_and_email_fields(self):
        s = Staff.objects.using("scrub").create(
            email="real.person@morrissheetmetal.co.nz",
            first_name="Real",
            last_name="Person",
            preferred_name="Realperson",
            xero_user_id="aaaa1111-2222-3333-4444-555566667777",
        )
        original_password = s.password  # hashed Django password string
        original_xero_user_id = s.xero_user_id

        _scrub_staff()

        row = Staff.objects.using("scrub").get(id=s.id)
        self.assertNotEqual(row.email, "real.person@morrissheetmetal.co.nz")
        self.assertNotEqual(row.first_name, "Real")
        self.assertNotEqual(row.last_name, "Person")
        self.assertTrue(row.email.endswith("@example.com"))
        # Today's flow leaves these alone — preserve that exactly.
        self.assertEqual(row.xero_user_id, original_xero_user_id)
        self.assertEqual(row.password, original_password)

    def test_scrub_generates_unique_emails(self):
        for i in range(5):
            Staff.objects.using("scrub").create(
                email=f"x{i}@morrissheetmetal.co.nz",
                first_name=f"F{i}",
                last_name=f"L{i}",
                preferred_name=None,
            )
        _scrub_staff()
        emails = set(Staff.objects.using("scrub").values_list("email", flat=True))
        self.assertEqual(len(emails), 5)


class ScrubClientsTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def _seed_company_defaults(self):
        from apps.workflow.models import CompanyDefaults

        CompanyDefaults.objects.using("scrub").all().delete()
        CompanyDefaults.objects.using("scrub").create(
            id=1,
            shop_client_name="Shop Co",
            test_client_name="Test Client",
            company_name="Demo Co",
        )

    def test_preserved_clients_untouched(self):
        from django.utils import timezone

        from apps.client.models import Client
        from apps.workflow.services.db_scrubber import _scrub_clients

        self._seed_company_defaults()
        now = timezone.now()
        shop = Client.objects.using("scrub").create(
            name="Shop Co",
            email="shop@real.example",
            phone="+64 1 234",
            xero_last_modified=now,
            raw_json={"_name": "Shop Co", "_email_address": "shop@real.example"},
        )
        Client.objects.using("scrub").create(
            name="Real Customer Ltd",
            email="bill@realcustomer.co.nz",
            phone="+64 9 876",
            xero_last_modified=now,
            raw_json={"_name": "Real Customer Ltd"},
        )

        _scrub_clients()

        shop.refresh_from_db(using="scrub")
        self.assertEqual(shop.name, "Shop Co")
        self.assertEqual(shop.email, "shop@real.example")
        self.assertEqual(shop.raw_json["_name"], "Shop Co")

        other = Client.objects.using("scrub").exclude(name="Shop Co").get()
        self.assertNotEqual(other.name, "Real Customer Ltd")
        self.assertNotEqual(other.email, "bill@realcustomer.co.nz")

    def test_only_configured_raw_json_paths_changed(self):
        from django.utils import timezone

        from apps.client.models import Client
        from apps.workflow.services.db_scrubber import _scrub_clients

        self._seed_company_defaults()
        Client.objects.using("scrub").create(
            name="Real Co",
            email="a@b.c",
            xero_last_modified=timezone.now(),
            raw_json={
                "_name": "Real Co",
                "_email_address": "a@b.c",
                "_bank_account_details": "1234-56-789",
                "_phones": [
                    {"_phone_number": "+64 1 111"},
                    {"_phone_number": "+64 2 222"},
                ],
                "_batch_payments": {
                    "_bank_account_number": "999-888-777",
                    "_bank_account_name": "Real Co Ltd",
                },
                "_unrelated_field": "keep me",
                "_address_line_1": "1 Real Street",
            },
        )

        _scrub_clients()

        c = Client.objects.using("scrub").get()
        self.assertNotEqual(c.raw_json["_name"], "Real Co")
        self.assertNotEqual(c.raw_json["_email_address"], "a@b.c")
        self.assertNotEqual(c.raw_json["_bank_account_details"], "1234-56-789")
        self.assertNotEqual(c.raw_json["_phones"][0]["_phone_number"], "+64 1 111")
        self.assertNotEqual(c.raw_json["_phones"][1]["_phone_number"], "+64 2 222")
        self.assertNotEqual(
            c.raw_json["_batch_payments"]["_bank_account_number"], "999-888-777"
        )
        self.assertNotEqual(
            c.raw_json["_batch_payments"]["_bank_account_name"], "Real Co Ltd"
        )
        # Untouched paths survive verbatim.
        self.assertEqual(c.raw_json["_unrelated_field"], "keep me")
        self.assertEqual(c.raw_json["_address_line_1"], "1 Real Street")

    def test_top_level_fields_not_in_pii_config_are_left_alone(self):
        from django.utils import timezone

        from apps.client.models import Client
        from apps.workflow.services.db_scrubber import _scrub_clients

        self._seed_company_defaults()
        Client.objects.using("scrub").create(
            name="Real Co",
            email="a@b.c",
            xero_last_modified=timezone.now(),
            address="1 Real Street",
            all_phones=["+64 1 111", "+64 2 222"],
            additional_contact_persons=[{"name": "Real Person", "email": "rp@x.co"}],
        )

        _scrub_clients()

        c = Client.objects.using("scrub").get()
        # Today's PII_CONFIG does NOT include these — preserve that.
        self.assertEqual(c.address, "1 Real Street")
        self.assertEqual(c.all_phones, ["+64 1 111", "+64 2 222"])
        self.assertEqual(
            c.additional_contact_persons, [{"name": "Real Person", "email": "rp@x.co"}]
        )

    def test_contact_anonymised_only_on_configured_fields(self):
        from django.utils import timezone

        from apps.client.models import Client, ClientContact
        from apps.workflow.services.db_scrubber import _scrub_clients

        self._seed_company_defaults()
        c = Client.objects.using("scrub").create(
            name="Real Co", email="a@b.c", xero_last_modified=timezone.now()
        )
        ClientContact.objects.using("scrub").create(
            client=c,
            name="Real Name",
            email="real@x.co",
            phone="123",
            position="Manager",
            notes="real note about real person",
        )

        _scrub_clients()

        cc = ClientContact.objects.using("scrub").get()
        self.assertNotEqual(cc.name, "Real Name")
        self.assertNotEqual(cc.email, "real@x.co")
        self.assertNotEqual(cc.phone, "123")
        # Today's PII_CONFIG does NOT include position/notes.
        self.assertEqual(cc.position, "Manager")
        self.assertEqual(cc.notes, "real note about real person")
