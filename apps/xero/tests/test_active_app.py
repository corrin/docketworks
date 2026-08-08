"""Active-app resolution, swap, and credential wipe.

Business risk covered: a stale tenant-id cache or a stale in-process ApiClient
after a credential swap silently points Xero calls at the wrong app — the swap
must invalidate both, and restart the sibling workers whose singletons it
cannot reach.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.xero import active_app, auth
from apps.xero.active_app import (
    NoActiveXeroAppError,
    get_active_app,
    swap_active,
    wipe_tokens_and_quota,
)
from apps.xero.constants import TENANT_ID_CACHE_KEY
from apps.xero.models import XeroApp

from .conftest import make_xero_app


@pytest.mark.django_db
class TestGetActiveApp:
    def test_returns_active_row(self) -> None:
        a = make_xero_app(client_id="a1", is_active=True)
        make_xero_app(client_id="b1", is_active=False)
        assert get_active_app().id == a.id

    def test_no_active_row_raises(self) -> None:
        make_xero_app(client_id="a1", is_active=False)
        with pytest.raises(NoActiveXeroAppError):
            get_active_app()


@pytest.mark.django_db
class TestSwapActive:
    def test_swaps_atomically(self) -> None:
        a = make_xero_app(client_id="a1", is_active=True)
        b = make_xero_app(client_id="b1", is_active=False)
        with patch("apps.xero.active_app._restart_sibling_workers"):
            result = swap_active(b.id)
        a.refresh_from_db()
        b.refresh_from_db()
        assert not a.is_active
        assert b.is_active
        assert result.id == b.id

    def test_swap_to_already_active_is_idempotent(self) -> None:
        a = make_xero_app(client_id="a1", is_active=True)
        with patch("apps.xero.active_app._restart_sibling_workers"):
            result = swap_active(a.id)
        a.refresh_from_db()
        assert a.is_active
        assert result.id == a.id

    def test_swap_unknown_id_raises(self) -> None:
        with pytest.raises(XeroApp.DoesNotExist):
            swap_active(uuid.uuid4())

    def test_swap_invalidates_tenant_id_cache(self) -> None:
        # Without this invalidation the next get_tenant_id() returns the
        # prior app's tenant under the new app's credentials.
        make_xero_app(client_id="a1", is_active=True)
        b = make_xero_app(client_id="b1", is_active=False)
        cache.set(TENANT_ID_CACHE_KEY, "tenant-from-a")
        with patch("apps.xero.active_app._restart_sibling_workers"):
            swap_active(b.id)
        assert cache.get(TENANT_ID_CACHE_KEY) is None

    def test_swap_resets_in_process_singleton(self) -> None:
        # The caller's auth.api_client must be invalidated so the next call
        # rebuilds against the now-active row.
        make_xero_app(client_id="a1", is_active=True)
        b = make_xero_app(client_id="b1", is_active=False)

        with (
            patch.object(auth, "_reset_api_client") as mock_reset,
            patch.object(active_app, "_restart_sibling_workers"),
        ):
            active_app.swap_active(b.id)
        mock_reset.assert_called_once()

    def test_swap_dispatches_systemctl_restart(self) -> None:
        # In a production-like env (INSTANCE set), swap fires a detached
        # `sudo systemctl restart` for the sibling worker units. The unit
        # names use the instance slug ("msm-prod"), NOT DB_NAME
        # ("dw_msm_prod") — they diverged in instance.sh.
        make_xero_app(client_id="a1", is_active=True)
        b = make_xero_app(client_id="b1", is_active=False)

        with (
            patch("apps.xero.active_app.subprocess.Popen") as mock_popen,
            patch("apps.xero.active_app.os.getenv", return_value="msm-prod"),
        ):
            active_app.swap_active(b.id)

        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        assert cmd[:3] == ["sudo", "systemctl", "restart"]
        assert set(cmd[3:]) == {
            "gunicorn-msm-prod.service",
            "celery-beat-msm-prod.service",
            "celery-worker-msm-prod.service",
        }
        assert kwargs.get("start_new_session")

    def test_swap_reads_instance_env_not_db_name(self) -> None:
        # Regression guard: the restart used to read DB_NAME by mistake,
        # which produced unit names like "gunicorn-dw_msm_prod.service"
        # that don't exist on disk — restart silently no-op'd. Pin that
        # the env var read is INSTANCE.
        make_xero_app(client_id="a1", is_active=True)
        b = make_xero_app(client_id="b1", is_active=False)

        captured: dict[str, str] = {}

        def fake_getenv(name: str, default: str | None = None) -> str:
            del default  # os.getenv signature; unused
            captured["name"] = name
            return "msm-prod"

        with (
            patch("apps.xero.active_app.subprocess.Popen"),
            patch("apps.xero.active_app.os.getenv", side_effect=fake_getenv),
        ):
            active_app.swap_active(b.id)

        assert captured["name"] == "INSTANCE"

    def test_swap_skips_restart_in_dev(self) -> None:
        # No INSTANCE → no systemctl call. In-process singleton reset still happens.
        make_xero_app(client_id="a1", is_active=True)
        b = make_xero_app(client_id="b1", is_active=False)

        with (
            patch("apps.xero.active_app.subprocess.Popen") as mock_popen,
            patch("apps.xero.active_app.os.getenv", return_value=None),
        ):
            active_app.swap_active(b.id)

        mock_popen.assert_not_called()


@pytest.mark.django_db
class TestWipeTokensAndQuota:
    def test_wipes_token_and_quota_fields(self) -> None:
        row = make_xero_app(
            client_id="a1",
            access_token="aaa",
            refresh_token="rrr",
            token_type="Bearer",
            expires_at=datetime.now(UTC),
            scope="x",
            day_remaining=42,
            minute_remaining=10,
            snapshot_at=datetime.now(UTC),
            last_429_at=datetime.now(UTC),
        )
        wipe_tokens_and_quota(row)
        row.refresh_from_db()
        for field in [
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
            assert getattr(row, field) is None, field

    def test_wipe_invalidates_tenant_id_cache(self) -> None:
        # Same reasoning as the swap test — credentials can change without
        # the active row flipping (e.g. operator edits client_id), and the
        # global tenant cache must drop in lockstep.
        row = make_xero_app(client_id="a1")
        cache.set(TENANT_ID_CACHE_KEY, "stale-tenant")
        wipe_tokens_and_quota(row)
        assert cache.get(TENANT_ID_CACHE_KEY) is None
