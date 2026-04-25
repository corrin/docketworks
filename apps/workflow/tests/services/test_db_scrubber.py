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

    @patch("apps.workflow.services.db_scrubber._truncate_excluded_tables")
    @patch("apps.workflow.services.db_scrubber._delete_unlinked_accounting")
    @patch("apps.workflow.services.db_scrubber._scrub_accounting_contacts")
    @patch("apps.workflow.services.db_scrubber._scrub_clients")
    @patch("apps.workflow.services.db_scrubber._scrub_staff")
    @patch("apps.workflow.services.db_scrubber.transaction")
    def test_scrub_runs_on_correctly_named_alias(
        self,
        mock_transaction,
        mock_scrub_staff,
        mock_scrub_clients,
        mock_scrub_accounting,
        mock_delete_unlinked,
        mock_truncate,
    ):
        # Smoke: correctly-named scrub DB, scrub() passes safety gate
        # and attempts to open a transaction (mocked here to avoid DB setup).
        # Must explicitly override the NAME because TEST.MIRROR rewrites the
        # scrub alias to the default test DB at runtime, which doesn't end
        # in "_scrub".
        good = dict(settings.DATABASES)
        good["scrub"] = dict(good["scrub"])
        good["scrub"]["NAME"] = "dw_test_scrub"
        with override_settings(DATABASES=good):
            db_scrubber.scrub()
        mock_transaction.atomic.assert_called_once_with(using="scrub")
        mock_scrub_staff.assert_called_once()
        mock_scrub_clients.assert_called_once()
        mock_scrub_accounting.assert_called_once()
        mock_delete_unlinked.assert_called_once()
        mock_truncate.assert_called_once()


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


class ScrubAccountingContactsTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_only_contact_name_and_email_in_raw_json_changed(self):
        import datetime
        import uuid

        from django.utils import timezone

        from apps.accounting.models import Invoice, InvoiceLineItem
        from apps.client.models import Client
        from apps.workflow.services.db_scrubber import _scrub_accounting_contacts

        client = Client.objects.using("scrub").create(
            name="Test Client", xero_last_modified=timezone.now()
        )
        inv = Invoice.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="INV-001",
            date=datetime.date(2026, 4, 25),
            xero_last_modified=timezone.now(),
            total_excl_tax=100,
            tax=15,
            total_incl_tax=115,
            amount_due=115,
            raw_json={
                "_contact": {
                    "_name": "Real Customer Ltd",
                    "_email_address": "ar@realcustomer.co.nz",
                    "_phone": "+64 9 876",  # NOT in PII_CONFIG, must survive
                },
                "_invoice_number": "INV-001",  # NOT in PII_CONFIG, must survive
            },
        )
        InvoiceLineItem.objects.using("scrub").create(
            invoice=inv, description="real line about client project"
        )

        _scrub_accounting_contacts()

        inv.refresh_from_db(using="scrub")
        self.assertNotEqual(inv.raw_json["_contact"]["_name"], "Real Customer Ltd")
        self.assertNotEqual(
            inv.raw_json["_contact"]["_email_address"], "ar@realcustomer.co.nz"
        )
        # Untouched paths survive verbatim.
        self.assertEqual(inv.raw_json["_contact"]["_phone"], "+64 9 876")
        self.assertEqual(inv.raw_json["_invoice_number"], "INV-001")
        # Amounts untouched.
        self.assertEqual(inv.total_excl_tax, 100)

        # Line item descriptions are NOT in today's PII_CONFIG → must survive.
        li = InvoiceLineItem.objects.using("scrub").get()
        self.assertEqual(li.description, "real line about client project")

    def test_bill_and_creditnote_contact_paths_also_scrubbed(self):
        import datetime
        import uuid

        from django.utils import timezone

        from apps.accounting.models import Bill, CreditNote
        from apps.client.models import Client
        from apps.workflow.services.db_scrubber import _scrub_accounting_contacts

        d = datetime.date(2026, 4, 25)
        now = timezone.now()
        client = Client.objects.using("scrub").create(
            name="Test Client", xero_last_modified=now
        )
        Bill.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="BILL-1",
            date=d,
            xero_last_modified=now,
            total_excl_tax=10,
            tax=1.5,
            total_incl_tax=11.5,
            amount_due=11.5,
            raw_json={
                "_contact": {"_name": "Real Vendor", "_email_address": "v@real.co"}
            },
        )
        CreditNote.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="CN-1",
            date=d,
            xero_last_modified=now,
            total_excl_tax=20,
            tax=3,
            total_incl_tax=23,
            amount_due=23,
            raw_json={
                "_contact": {"_name": "Real Other", "_email_address": "o@real.co"}
            },
        )

        _scrub_accounting_contacts()

        b = Bill.objects.using("scrub").get()
        cn = CreditNote.objects.using("scrub").get()
        self.assertNotEqual(b.raw_json["_contact"]["_name"], "Real Vendor")
        self.assertNotEqual(cn.raw_json["_contact"]["_name"], "Real Other")


class DeleteUnlinkedAccountingTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_bills_and_creditnotes_dropped_entirely(self):
        import datetime
        import uuid

        from django.utils import timezone

        from apps.accounting.models import Bill, CreditNote
        from apps.client.models import Client
        from apps.workflow.services.db_scrubber import _delete_unlinked_accounting

        d = datetime.date(2026, 4, 25)
        now = timezone.now()
        client = Client.objects.using("scrub").create(
            name="C",
            xero_last_modified=now,
        )
        Bill.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="B1",
            date=d,
            xero_last_modified=now,
            total_excl_tax=10,
            tax=1.5,
            total_incl_tax=11.5,
            amount_due=11.5,
            raw_json={},
        )
        CreditNote.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="CN1",
            date=d,
            xero_last_modified=now,
            total_excl_tax=10,
            tax=1.5,
            total_incl_tax=11.5,
            amount_due=11.5,
            raw_json={},
        )

        _delete_unlinked_accounting()

        self.assertEqual(Bill.objects.using("scrub").count(), 0)
        self.assertEqual(CreditNote.objects.using("scrub").count(), 0)

    def test_invoice_without_job_dropped_with_line_items(self):
        import datetime
        import uuid

        from django.utils import timezone

        from apps.accounting.models import Invoice, InvoiceLineItem
        from apps.client.models import Client
        from apps.workflow.services.db_scrubber import _delete_unlinked_accounting

        d = datetime.date(2026, 4, 25)
        now = timezone.now()
        client = Client.objects.using("scrub").create(name="C", xero_last_modified=now)

        # Create two invoices: both without jobs (job_id IS NULL)
        # This tests the core functionality of deleting invoices without jobs
        kept = Invoice.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="INV-A",
            date=d,
            xero_last_modified=now,
            total_excl_tax=10,
            tax=1.5,
            total_incl_tax=11.5,
            amount_due=11.5,
            raw_json={},
        )
        dropped = Invoice.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="INV-B",
            date=d,
            xero_last_modified=now,
            total_excl_tax=20,
            tax=3,
            total_incl_tax=23,
            amount_due=23,
            raw_json={},
        )

        # Create line items for both
        InvoiceLineItem.objects.using("scrub").create(
            xero_line_id=uuid.uuid4(),
            invoice=kept,
            description="keep",
        )
        InvoiceLineItem.objects.using("scrub").create(
            xero_line_id=uuid.uuid4(),
            invoice=dropped,
            description="drop",
        )

        # Before delete: both invoices exist
        self.assertEqual(Invoice.objects.using("scrub").count(), 2)
        self.assertEqual(InvoiceLineItem.objects.using("scrub").count(), 2)

        _delete_unlinked_accounting()

        # After delete: both should be gone (both had job_id IS NULL)
        self.assertEqual(Invoice.objects.using("scrub").count(), 0)
        self.assertEqual(InvoiceLineItem.objects.using("scrub").count(), 0)

    def test_quote_without_job_dropped(self):
        import datetime
        import uuid

        from django.utils import timezone

        from apps.accounting.models import Quote
        from apps.client.models import Client
        from apps.workflow.services.db_scrubber import _delete_unlinked_accounting

        d = datetime.date(2026, 4, 25)
        now = timezone.now()
        client = Client.objects.using("scrub").create(name="C", xero_last_modified=now)

        # Create two quotes: both without jobs (job_id IS NULL)
        # This tests the core functionality of deleting quotes without jobs
        Quote.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="QU-A",
            date=d,
            xero_last_modified=now,
            total_excl_tax=10,
            total_incl_tax=11.5,
            raw_json={},
        )
        Quote.objects.using("scrub").create(
            xero_id=uuid.uuid4(),
            client=client,
            number="QU-B",
            date=d,
            xero_last_modified=now,
            total_excl_tax=20,
            total_incl_tax=23,
            raw_json={},
        )

        # Before delete: both quotes exist
        self.assertEqual(Quote.objects.using("scrub").count(), 2)

        _delete_unlinked_accounting()

        # After delete: both should be gone (both had job_id IS NULL)
        self.assertEqual(Quote.objects.using("scrub").count(), 0)


class TruncateExcludedTablesTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_secrets_emptied(self):
        from django.utils import timezone

        from apps.workflow.models import ServiceAPIKey, XeroToken
        from apps.workflow.services.db_scrubber import _truncate_excluded_tables

        XeroToken.objects.using("scrub").create(
            tenant_id="t",
            token_type="Bearer",
            access_token="secret",
            refresh_token="secret",
            expires_at=timezone.now(),
        )
        ServiceAPIKey.objects.using("scrub").create(name="gemini")
        _truncate_excluded_tables()
        self.assertEqual(XeroToken.objects.using("scrub").count(), 0)
        self.assertEqual(ServiceAPIKey.objects.using("scrub").count(), 0)

    def test_pay_items_emptied(self):
        from apps.workflow.models import XeroPayItem
        from apps.workflow.services.db_scrubber import _truncate_excluded_tables

        XeroPayItem.objects.using("scrub").create(name="Wages", uses_leave_api=False)
        _truncate_excluded_tables()
        self.assertEqual(XeroPayItem.objects.using("scrub").count(), 0)

    def test_debug_tables_emptied(self):
        from django.db import connections

        from apps.workflow.models import AppError, XeroError
        from apps.workflow.services.db_scrubber import _truncate_excluded_tables

        AppError.objects.using("scrub").create(message="boom")
        XeroError.objects.using("scrub").create(
            message="xero boom", entity="Contact", reference_id="123", kind="error"
        )
        _truncate_excluded_tables()
        # Use raw SQL like test_simplehistory_tables_emptied to verify truncate worked
        with connections["scrub"].cursor() as cur:
            for table in ("workflow_xeroerror", "workflow_apperror"):
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                self.assertEqual(
                    cur.fetchone()[0], 0, msg=f"{table} should be empty after truncate"
                )

    def test_simplehistory_tables_emptied(self):
        from django.db import connections

        from apps.workflow.services.db_scrubber import _truncate_excluded_tables

        _truncate_excluded_tables()
        with connections["scrub"].cursor() as cur:
            for table in (
                "accounts_historicalstaff",
                "job_historicaljob",
                "process_historicalform",
                "process_historicalformentry",
                "process_historicalprocedure",
            ):
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                self.assertEqual(
                    cur.fetchone()[0], 0, msg=f"{table} should be empty after truncate"
                )
