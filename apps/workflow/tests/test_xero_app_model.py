"""Tests for the XeroApp model — partial unique constraint on is_active,
unique client_id, and basic field defaults.

XeroApp replaces XeroToken: one row per registered Xero app, exactly one
marked is_active=True at a time.
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.workflow.models import XeroApp


class XeroAppModelTests(TestCase):
    def _row(self, **overrides):
        defaults = {
            "label": "Primary",
            "client_id": "abc123",
            "client_secret": "shh",
            "redirect_uri": "https://example.test/callback",
            "is_active": False,
        }
        defaults.update(overrides)
        return XeroApp.objects.create(**defaults)

    def test_create_minimal_row(self):
        row = self._row()
        self.assertEqual(row.label, "Primary")
        self.assertFalse(row.is_active)
        self.assertIsNone(row.access_token)
        self.assertIsNone(row.refresh_token)
        self.assertIsNone(row.day_remaining)
        self.assertIsNone(row.snapshot_at)

    def test_client_id_unique(self):
        self._row(client_id="abc123", label="A")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._row(client_id="abc123", label="B")

    def test_at_most_one_active_row(self):
        self._row(client_id="abc1", label="A", is_active=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._row(client_id="abc2", label="B", is_active=True)

    def test_two_inactive_rows_allowed(self):
        self._row(client_id="abc1", label="A", is_active=False)
        self._row(client_id="abc2", label="B", is_active=False)
        self.assertEqual(XeroApp.objects.count(), 2)

    def test_can_swap_active_via_two_updates(self):
        # Real swaps go through swap_active() which clears the old active
        # row first, but the constraint must permit that pattern.
        a = self._row(client_id="abc1", label="A", is_active=True)
        b = self._row(client_id="abc2", label="B", is_active=False)
        a.is_active = False
        a.save()
        b.is_active = True
        b.save()
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertTrue(b.is_active)
