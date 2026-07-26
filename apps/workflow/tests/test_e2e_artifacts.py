"""Tests for ignoring Xero objects created by finished E2E runs.

E2E runs write real Contacts, Invoices and Quotes to a development Xero org.
Those survive the post-run database restore, and the hourly Xero sync would
otherwise replay them into the clean database. These tests pin the two
conditions that together decide the skip, and the gate that stops it ever
running outside dev.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.workflow.services.e2e_artifacts import (
    TEST_COMPANY_NAME,
    TEST_DATA_PREFIX,
    drop_e2e_artifacts,
)


def _contact(name: str, updated_at: datetime) -> SimpleNamespace:
    """An inbound Xero contact: carries its own company name."""
    return SimpleNamespace(name=name, updated_date_utc=updated_at)


def _invoice(contact_name: str, updated_at: datetime) -> SimpleNamespace:
    """An inbound Xero document: carries its company via an embedded contact."""
    return SimpleNamespace(
        contact=SimpleNamespace(name=contact_name),
        updated_date_utc=updated_at,
    )


class E2EWindowFileTestCase(TestCase):
    """Base that points the module at a temporary windows file."""

    def setUp(self) -> None:
        self.now = timezone.now()
        self.run_start = self.now - timedelta(minutes=30)
        self.run_end = self.now - timedelta(minutes=5)
        self.during_run = self.now - timedelta(minutes=20)

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.windows_file = Path(self._tmp.name) / "sync-windows.json"

        patcher = patch(
            "apps.workflow.services.e2e_artifacts.E2E_SYNC_WINDOWS_FILE",
            self.windows_file,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_window(self, *, ended: bool) -> None:
        self.windows_file.write_text(
            json.dumps(
                [
                    {
                        "run_id": "testrun1",
                        "started_at": self.run_start.isoformat(),
                        "ended_at": self.run_end.isoformat() if ended else None,
                    }
                ]
            )
        )


class DropE2EArtifactsTests(E2EWindowFileTestCase):
    def test_test_company_inside_closed_window_is_dropped(self) -> None:
        self.write_window(ended=True)
        item = _contact(f"{TEST_DATA_PREFIX} Company 123", self.during_run)

        self.assertEqual(drop_e2e_artifacts([item], "contacts"), [])

    @override_settings(PRODUCTION_LIKE=True)
    def test_production_like_never_drops_anything(self) -> None:
        """Every server is production_like; only DJANGO_ENV=local is not.

        Discarding inbound Xero data is only ever correct against a development
        org, so a stray windows file must not be enough to cause it.
        """
        self.write_window(ended=True)
        item = _contact(f"{TEST_DATA_PREFIX} Company 123", self.during_run)

        self.assertEqual(drop_e2e_artifacts([item], "contacts"), [item])

    def test_fixture_company_inside_closed_window_is_dropped(self) -> None:
        """The standing fixture company is test data too.

        Test jobs hang off it, so the invoices and quotes a run raises are its
        documents, not those of a [TEST]-prefixed company.
        """
        self.write_window(ended=True)
        item = _contact(TEST_COMPANY_NAME, self.during_run)

        self.assertEqual(drop_e2e_artifacts([item], "contacts"), [])

    def test_ordinary_company_inside_closed_window_is_kept(self) -> None:
        """The window alone must never suppress; this is the over-reach guard.

        A real Xero edit landing inside a run's window would otherwise be
        discarded, and because the sync cursor still advances it would never be
        fetched again.
        """
        self.write_window(ended=True)
        item = _contact("Morris Sheetmetal", self.during_run)

        self.assertEqual(drop_e2e_artifacts([item], "contacts"), [item])

    def test_test_company_outside_any_window_is_kept(self) -> None:
        self.write_window(ended=True)
        item = _contact(f"{TEST_DATA_PREFIX} Company 123", self.now)

        self.assertEqual(drop_e2e_artifacts([item], "contacts"), [item])

    def test_open_window_suppresses_nothing(self) -> None:
        """The mid-run guarantee.

        While a run executes, inbound Xero data must behave exactly as it does
        in production — that round trip is what the run exercises. Fails if the
        ended_at condition is ever dropped.
        """
        self.write_window(ended=False)
        item = _contact(f"{TEST_DATA_PREFIX} Company 123", self.during_run)

        self.assertEqual(drop_e2e_artifacts([item], "contacts"), [item])

    def test_document_is_dropped_with_its_contact(self) -> None:
        """A suppressed contact's documents must go with it.

        The invoice, quote and purchase-order importers resolve their contact
        through resolve_company_from_xero_contact, which raises rather than
        skips when the company cannot be synced. Leaving the document behind
        would abort the whole sync run.
        """
        self.write_window(ended=True)
        test_contact = _contact(f"{TEST_DATA_PREFIX} Company 123", self.during_run)
        its_invoice = _invoice(f"{TEST_DATA_PREFIX} Company 123", self.during_run)

        self.assertEqual(drop_e2e_artifacts([test_contact, its_invoice], "mixed"), [])

    def test_absent_windows_file_suppresses_nothing(self) -> None:
        """The ordinary state of any machine that has never run E2E."""
        item = _contact(f"{TEST_DATA_PREFIX} Company 123", self.during_run)

        self.assertEqual(drop_e2e_artifacts([item], "contacts"), [item])
