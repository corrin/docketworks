"""Tests for active_app helpers: get_active_app, swap_active,
wipe_tokens_and_quota, and the rebuild-on-swap behaviour of
get_active_client."""

import uuid
from datetime import datetime
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase

from apps.workflow.models import XeroApp


def _row(**overrides):
    defaults = {
        "label": "A",
        "client_id": "c-a",
        "client_secret": "s",
        "redirect_uri": "https://example.test/cb",
        "is_active": False,
    }
    defaults.update(overrides)
    return XeroApp.objects.create(**defaults)


class GetActiveAppTests(TestCase):
    def test_returns_active_row(self):
        from apps.workflow.api.xero.active_app import get_active_app

        a = _row(client_id="a1", is_active=True)
        _row(client_id="b1", is_active=False)
        self.assertEqual(get_active_app().id, a.id)

    def test_no_active_row_raises(self):
        from apps.workflow.api.xero.active_app import (
            NoActiveXeroApp,
            get_active_app,
        )

        _row(client_id="a1", is_active=False)
        with self.assertRaises(NoActiveXeroApp):
            get_active_app()


class SwapActiveTests(TestCase):
    def test_swaps_atomically(self):
        from apps.workflow.api.xero.active_app import swap_active

        a = _row(client_id="a1", is_active=True)
        b = _row(client_id="b1", is_active=False)
        result = swap_active(b.id)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertTrue(b.is_active)
        self.assertEqual(result.id, b.id)

    def test_swap_to_already_active_is_idempotent(self):
        from apps.workflow.api.xero.active_app import swap_active

        a = _row(client_id="a1", is_active=True)
        result = swap_active(a.id)
        a.refresh_from_db()
        self.assertTrue(a.is_active)
        self.assertEqual(result.id, a.id)

    def test_swap_unknown_id_raises(self):
        from apps.workflow.api.xero.active_app import swap_active

        with self.assertRaises(XeroApp.DoesNotExist):
            swap_active(uuid.uuid4())


class WipeTokensAndQuotaTests(TestCase):
    def test_wipes_token_and_quota_fields(self):
        from apps.workflow.api.xero.active_app import wipe_tokens_and_quota

        row = _row(
            client_id="a1",
            tenant_id="t",
            access_token="aaa",
            refresh_token="rrr",
            token_type="Bearer",
            expires_at=datetime.now(dt_timezone.utc),
            scope="x",
            day_remaining=42,
            minute_remaining=10,
            snapshot_at=datetime.now(dt_timezone.utc),
            last_429_at=datetime.now(dt_timezone.utc),
        )
        wipe_tokens_and_quota(row)
        row.refresh_from_db()
        for field in [
            "tenant_id",
            "access_token",
            "refresh_token",
            "token_type",
            "expires_at",
            "scope",
            "day_remaining",
            "minute_remaining",
            "snapshot_at",
            "last_429_at",
        ]:
            self.assertIsNone(getattr(row, field), field)


class GetActiveClientRebuildTests(TestCase):
    """The cached client is keyed by app_id; flipping which row is active
    must cause the next get_active_client() to rebuild."""

    def test_rebuilds_when_active_id_changes(self):
        from apps.workflow.api.xero import active_app

        active_app._reset_client_cache()
        _row(client_id="a1", is_active=True)
        b = _row(client_id="b1", is_active=False)

        with patch.object(active_app, "build_api_client") as mock_build:
            sentinel_a = object()
            sentinel_b = object()
            mock_build.side_effect = [sentinel_a, sentinel_b]

            client_a = active_app.get_active_client()
            client_a_again = active_app.get_active_client()
            self.assertIs(client_a, sentinel_a)
            self.assertIs(client_a_again, sentinel_a)
            self.assertEqual(mock_build.call_count, 1)

            active_app.swap_active(b.id)
            client_b = active_app.get_active_client()
            self.assertIs(client_b, sentinel_b)
            self.assertEqual(mock_build.call_count, 2)

        active_app._reset_client_cache()
