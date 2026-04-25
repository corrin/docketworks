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

    @patch("apps.workflow.services.db_scrubber._scrub_staff")
    @patch("apps.workflow.services.db_scrubber.transaction")
    def test_scrub_runs_on_correctly_named_alias(
        self, mock_transaction, mock_scrub_staff
    ):
        # Smoke: correctly-named scrub DB, scrub() passes safety gate
        # and attempts to open a transaction (mocked here to avoid DB setup).
        db_scrubber.scrub()
        mock_transaction.atomic.assert_called_once_with(using="scrub")
        mock_scrub_staff.assert_called_once()


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
