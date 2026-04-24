from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.workflow.services import db_scrubber


class ScrubSafetyGateTests(SimpleTestCase):

    def test_scrub_refuses_if_alias_name_does_not_end_in_scrub(self):
        bad = dict(settings.DATABASES)
        bad["scrub"] = dict(bad["scrub"])
        bad["scrub"]["NAME"] = "dw_yourco_prod"
        with override_settings(DATABASES=bad):
            with self.assertRaisesRegex(RuntimeError, "must end in '_scrub'"):
                db_scrubber.scrub()

    @patch("apps.workflow.services.db_scrubber.transaction")
    def test_scrub_runs_on_correctly_named_alias(self, mock_transaction):
        # Smoke: correctly-named scrub DB, scrub() passes safety gate
        # and attempts to open a transaction (mocked here to avoid DB setup).
        db_scrubber.scrub()
        mock_transaction.atomic.assert_called_once_with(using="scrub")
