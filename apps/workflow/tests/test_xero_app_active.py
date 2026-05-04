"""Tests for active_app helpers: get_active_app, swap_active,
wipe_tokens_and_quota."""

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
        with patch("apps.workflow.api.xero.active_app._restart_sibling_workers"):
            result = swap_active(b.id)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertTrue(b.is_active)
        self.assertEqual(result.id, b.id)

    def test_swap_to_already_active_is_idempotent(self):
        from apps.workflow.api.xero.active_app import swap_active

        a = _row(client_id="a1", is_active=True)
        with patch("apps.workflow.api.xero.active_app._restart_sibling_workers"):
            result = swap_active(a.id)
        a.refresh_from_db()
        self.assertTrue(a.is_active)
        self.assertEqual(result.id, a.id)

    def test_swap_unknown_id_raises(self):
        from apps.workflow.api.xero.active_app import swap_active

        with self.assertRaises(XeroApp.DoesNotExist):
            swap_active(uuid.uuid4())

    def test_swap_invalidates_tenant_id_cache(self):
        # Without this invalidation the next get_tenant_id() returns the
        # prior app's tenant under the new app's credentials.
        from django.core.cache import cache

        from apps.workflow.api.xero.active_app import swap_active
        from apps.workflow.api.xero.constants import TENANT_ID_CACHE_KEY

        a = _row(client_id="a1", is_active=True)  # noqa: F841
        b = _row(client_id="b1", is_active=False)
        cache.set(TENANT_ID_CACHE_KEY, "tenant-from-a")
        with patch("apps.workflow.api.xero.active_app._restart_sibling_workers"):
            swap_active(b.id)
        self.assertIsNone(cache.get(TENANT_ID_CACHE_KEY))

    def test_swap_resets_in_process_singleton(self):
        # The caller's auth.api_client must be invalidated so the next call
        # rebuilds against the now-active row.
        from apps.workflow.api.xero import active_app, auth

        _row(client_id="a1", is_active=True)
        b = _row(client_id="b1", is_active=False)

        with (
            patch.object(auth, "_reset_api_client") as mock_reset,
            patch.object(active_app, "_restart_sibling_workers"),
        ):
            active_app.swap_active(b.id)
        mock_reset.assert_called_once()

    def test_swap_dispatches_systemctl_restart(self):
        # In a production-like env (INSTANCE set), swap fires a detached
        # `sudo systemctl restart` for the sibling worker units. The unit
        # names use the instance slug ("msm-prod"), NOT DB_NAME
        # ("dw_msm_prod") — they diverged in instance.sh.
        from apps.workflow.api.xero import active_app

        _row(client_id="a1", is_active=True)
        b = _row(client_id="b1", is_active=False)

        with (
            patch("apps.workflow.api.xero.active_app.subprocess.Popen") as mock_popen,
            patch(
                "apps.workflow.api.xero.active_app.os.getenv",
                return_value="msm-prod",
            ),
        ):
            active_app.swap_active(b.id)

        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        self.assertEqual(cmd[:3], ["sudo", "systemctl", "restart"])
        self.assertEqual(
            set(cmd[3:]),
            {
                "gunicorn-msm-prod.service",
                "celery-beat-msm-prod.service",
                "celery-worker-msm-prod.service",
            },
        )
        self.assertTrue(kwargs.get("start_new_session"))

    def test_swap_reads_instance_env_not_db_name(self):
        # Regression guard: the restart used to read DB_NAME by mistake,
        # which produced unit names like "gunicorn-dw_msm_prod.service"
        # that don't exist on disk — restart silently no-op'd. Pin that
        # the env var read is INSTANCE.
        from apps.workflow.api.xero import active_app

        _row(client_id="a1", is_active=True)
        b = _row(client_id="b1", is_active=False)

        captured: dict = {}

        def fake_getenv(name, default=None):
            captured["name"] = name
            return "msm-prod"

        with (
            patch("apps.workflow.api.xero.active_app.subprocess.Popen"),
            patch(
                "apps.workflow.api.xero.active_app.os.getenv", side_effect=fake_getenv
            ),
        ):
            active_app.swap_active(b.id)

        self.assertEqual(captured["name"], "INSTANCE")

    def test_swap_skips_restart_in_dev(self):
        # No INSTANCE → no systemctl call. In-process singleton reset still happens.
        from apps.workflow.api.xero import active_app

        _row(client_id="a1", is_active=True)
        b = _row(client_id="b1", is_active=False)

        with (
            patch("apps.workflow.api.xero.active_app.subprocess.Popen") as mock_popen,
            patch("apps.workflow.api.xero.active_app.os.getenv", return_value=None),
        ):
            active_app.swap_active(b.id)

        mock_popen.assert_not_called()


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

    def test_wipe_invalidates_tenant_id_cache(self):
        # Same reasoning as the swap test — credentials can change without
        # the active row flipping (e.g. operator edits client_id), and the
        # global tenant cache must drop in lockstep.
        from django.core.cache import cache

        from apps.workflow.api.xero.active_app import wipe_tokens_and_quota
        from apps.workflow.api.xero.constants import TENANT_ID_CACHE_KEY

        row = _row(client_id="a1", tenant_id="t-1")
        cache.set(TENANT_ID_CACHE_KEY, "stale-tenant")
        wipe_tokens_and_quota(row)
        self.assertIsNone(cache.get(TENANT_ID_CACHE_KEY))


class ApiClientSingletonTests(TestCase):
    """auth.api_client is a stable proxy backed by a lazy singleton."""

    def test_proxy_is_stable(self):
        from apps.workflow.api.xero import auth

        # The proxy itself never changes — `from auth import api_client`
        # captures it once and stays valid across resets.
        self.assertIs(auth.api_client, auth.api_client)

    def test_lazy_build_on_attribute_access(self):
        from apps.workflow.api.xero import auth

        _row(client_id="a1", is_active=True, access_token="t", refresh_token="r")
        auth._reset_api_client()
        self.assertIsNone(auth._api_client)
        # Touch any attribute on the proxy → triggers _build() once.
        _ = auth.api_client.configuration
        self.assertIsNotNone(auth._api_client)
        first_underlying = auth._api_client
        _ = auth.api_client.configuration  # cached: same underlying
        self.assertIs(auth._api_client, first_underlying)
        auth._reset_api_client()

    def test_reset_forces_rebuild_on_next_access(self):
        from apps.workflow.api.xero import auth

        _row(client_id="a1", is_active=True, access_token="t", refresh_token="r")
        auth._reset_api_client()
        _ = auth.api_client.configuration
        first_underlying = auth._api_client
        auth._reset_api_client()
        _ = auth.api_client.configuration
        second_underlying = auth._api_client
        self.assertIsNot(first_underlying, second_underlying)
        auth._reset_api_client()

    def test_no_active_row_raises_on_access(self):
        from apps.workflow.api.xero import auth
        from apps.workflow.api.xero.active_app import NoActiveXeroApp

        # No XeroApp row at all. The proxy itself doesn't touch the DB,
        # but the first attribute access does.
        auth._reset_api_client()
        with self.assertRaises(NoActiveXeroApp):
            _ = auth.api_client.configuration
