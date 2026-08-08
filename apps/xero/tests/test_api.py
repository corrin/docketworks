"""The Xero HTTP surface: ping, disconnect, branding themes, app management.

Business risks covered: the ping payload is a contract with the E2E preflight
(missing ``xero_readonly`` fails the whole suite closed, and a production
client id must be visible before any spec writes); the app-management
endpoints are the break-glass credential rotation, where leaking a secret or
wiping the wrong row's tokens is an incident.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import Client, override_settings

from apps.accounting.types import DocumentTheme
from apps.core.errors import persist_app_error
from apps.core.models import AppError, CompanyDefaults
from apps.xero.models import XeroApp
from apps.xero.provider import XeroAccountingProvider

from .conftest import make_xero_app

pytestmark = pytest.mark.django_db

PING_URL = "/api/xero/ping/"
DISCONNECT_URL = "/api/xero/disconnect/"
THEMES_URL = "/api/xero/branding-themes/"
APPS_URL = "/api/xero/apps/"

_CREATE_PAYLOAD = {
    "label": "Secondary",
    "client_id": "c-new",
    "client_secret": "s-new",
    "redirect_uri": "https://example.test/cb",
    "webhook_key": "wh-new",
}


def _connected_app(**overrides: object) -> XeroApp:
    defaults: dict[str, object] = {
        "client_id": "c-a",
        "is_active": True,
        "access_token": "AT",
        "refresh_token": "RT",
        "token_type": "Bearer",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "scope": "accounting.contacts",
    }
    defaults.update(overrides)
    return make_xero_app(**defaults)  # type: ignore[arg-type]  # forwarded verbatim to the factory


class TestXeroPing:
    def test_requires_authentication(self, client: Client) -> None:
        assert client.get(PING_URL).status_code == 401

    @override_settings(XERO_READONLY=True)
    def test_not_connected_payload_carries_exact_keys(self, api: Client) -> None:
        response = api.get(PING_URL)

        assert response.status_code == 200
        assert response.json() == {
            "connected": False,
            "xero_readonly": True,
            "xero_production_client": False,
        }

    @override_settings(XERO_READONLY=False)
    def test_connected_with_valid_token(self, api: Client) -> None:
        _connected_app()

        body = api.get(PING_URL).json()

        assert body["connected"] is True
        assert body["xero_readonly"] is False

    @override_settings(PRODUCTION_XERO_CLIENT_IDS=["prod-client"], XERO_READONLY=False)
    def test_reports_production_xero_client_true(self, api: Client) -> None:
        _connected_app(client_id="Prod-Client")  # matching is case-insensitive

        assert api.get(PING_URL).json()["xero_production_client"] is True

    @override_settings(PRODUCTION_XERO_CLIENT_IDS=["prod-client"], XERO_READONLY=False)
    def test_reports_production_xero_client_false(self, api: Client) -> None:
        _connected_app(client_id="dev-client")

        assert api.get(PING_URL).json()["xero_production_client"] is False

    def test_refresh_failure_is_a_500_with_error_id_not_a_quiet_false(self, api: Client) -> None:
        """An operational failure must be distinguishable from not-connected."""
        exc = RuntimeError("refresh failed")
        app_error = persist_app_error(exc)
        before = AppError.objects.count()

        with patch("apps.xero.api.get_valid_token", side_effect=exc):
            response = api.get(PING_URL)

        assert response.status_code == 500
        body = response.json()
        assert body["connected"] is False
        # Fixed message: refresh failures can quote upstream responses, and
        # error_id already keys into the persisted detail.
        assert body["error"] == "Xero connection check failed; see error_id."
        assert body["error_id"] == str(app_error.id)
        # One failure is one row (ADR 0001) — the endpoint reuses the
        # pre-persisted error instead of writing a duplicate.
        assert AppError.objects.count() == before


class TestXeroDisconnect:
    def test_office_staff_only(self, non_office_api: Client) -> None:
        assert non_office_api.post(DISCONNECT_URL).status_code == 403

    @override_settings(XERO_READONLY=True)
    def test_wipes_active_row_tokens_and_reports_disconnected(self, api: Client) -> None:
        row = _connected_app()

        response = api.post(DISCONNECT_URL)

        assert response.status_code == 200
        assert response.json()["connected"] is False
        row.refresh_from_db()
        assert row.access_token is None
        assert row.refresh_token is None

    @override_settings(XERO_READONLY=True)
    def test_no_active_row_is_a_clean_no_op(self, api: Client) -> None:
        response = api.post(DISCONNECT_URL)

        assert response.status_code == 200
        assert response.json()["connected"] is False


class TestBrandingThemes:
    def test_without_xero_token_returns_401_redirect_payload(self, api: Client) -> None:
        response = api.get(THEMES_URL)

        assert response.status_code == 401
        assert response.json() == {
            "success": False,
            "redirect_to_auth": True,
            "message": "Your Xero session has expired. Please log in again.",
        }

    def test_returns_selector_contract(self, api: Client) -> None:
        theme_id = str(uuid.uuid4())
        provider = Mock()
        provider.list_document_themes.return_value = [
            DocumentTheme(external_id=theme_id, name="Sales Terms", is_default=True)
        ]
        with (
            patch("apps.xero.api.get_valid_token", return_value={"access_token": "t"}),
            patch("apps.xero.api.get_provider", return_value=provider),
        ):
            response = api.get(THEMES_URL)

        assert response.status_code == 200
        assert response.json() == [
            {"external_id": theme_id, "name": "Sales Terms", "is_default": True}
        ]

    def test_provider_preserves_xero_order_and_default(self) -> None:
        """sort_order 0 is Xero's default theme and must sort first."""
        api = Mock()
        # SimpleNamespace, not Mock: Mock(name=...) sets the mock's own name,
        # so a `name` attribute would come back as a child Mock, not a str.
        api.get_branding_themes.return_value = SimpleNamespace(
            branding_themes=[
                SimpleNamespace(
                    branding_theme_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    name="Secondary",
                    sort_order=2,
                ),
                SimpleNamespace(
                    branding_theme_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    name="Sales Terms",
                    sort_order=0,
                ),
            ]
        )
        with patch.object(XeroAccountingProvider, "_get_api", return_value=(api, "tenant-id")):
            themes = XeroAccountingProvider().list_document_themes()

        assert [theme.name for theme in themes] == ["Sales Terms", "Secondary"]
        assert themes[0].is_default
        assert not themes[1].is_default


class TestXeroAppsPermissions:
    def test_anonymous_unauthenticated_on_list(self, client: Client) -> None:
        assert client.get(APPS_URL).status_code == 401

    def test_non_office_staff_forbidden(self, non_office_api: Client) -> None:
        assert non_office_api.get(APPS_URL).status_code == 403
        assert (
            non_office_api.post(
                APPS_URL, data=_CREATE_PAYLOAD, content_type="application/json"
            ).status_code
            == 403
        )


class TestXeroAppsList:
    def test_list_returns_safe_fields_only(self, api: Client) -> None:
        _connected_app(
            label="Primary",
            access_token="SECRET-DO-NOT-LEAK",
            refresh_token="ALSO-SECRET",
            day_remaining=4321,
            minute_remaining=55,
        )

        response = api.get(APPS_URL)

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        row = body[0]
        assert row["label"] == "Primary"
        assert row["client_id"] == "c-a"
        assert row["is_active"] is True
        assert row["has_tokens"] is True
        assert row["day_remaining"] == 4321
        assert row["minute_remaining"] == 55
        # Forbidden surface — none of these may appear in the response:
        assert "client_secret" not in row
        assert "access_token" not in row
        assert "refresh_token" not in row
        assert "webhook_key" not in row


class TestXeroAppsCreate:
    def test_create_row_is_inactive_until_activated(self, api: Client) -> None:
        response = api.post(APPS_URL, data=_CREATE_PAYLOAD, content_type="application/json")

        assert response.status_code == 201
        body = response.json()
        assert body["is_active"] is False
        assert body["has_tokens"] is False
        app = XeroApp.objects.get(id=body["id"])
        assert app.client_secret == "s-new"
        assert app.webhook_key == "wh-new"

    def test_create_duplicate_client_id_returns_400(self, api: Client) -> None:
        make_xero_app(client_id="c-new")

        response = api.post(APPS_URL, data=_CREATE_PAYLOAD, content_type="application/json")

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    @pytest.mark.parametrize("missing", ["client_secret", "webhook_key"])
    def test_create_without_either_secret_rejected(self, api: Client, missing: str) -> None:
        """A row missing either secret is inert — reject it up front."""
        payload = {k: v for k, v in _CREATE_PAYLOAD.items() if k != missing}

        response = api.post(APPS_URL, data=payload, content_type="application/json")

        assert response.status_code == 422
        assert XeroApp.objects.count() == 0


class TestXeroAppsPatch:
    def _url(self, app: XeroApp) -> str:
        return f"{APPS_URL}{app.id}/"

    def test_patch_label_only_does_not_wipe_tokens(self, api: Client) -> None:
        row = _connected_app()

        response = api.patch(
            self._url(row), data={"label": "Renamed"}, content_type="application/json"
        )

        assert response.status_code == 200
        row.refresh_from_db()
        assert row.label == "Renamed"
        assert row.access_token == "AT"

    def test_patch_client_id_wipes_tokens_and_quota(self, api: Client) -> None:
        row = _connected_app(day_remaining=100, is_active=False)

        with patch("apps.xero.api._restart_sibling_workers"):
            response = api.patch(
                self._url(row), data={"client_id": "c-rotated"}, content_type="application/json"
            )

        assert response.status_code == 200
        assert response.json()["has_tokens"] is False
        row.refresh_from_db()
        assert row.client_id == "c-rotated"
        assert row.access_token is None
        assert row.day_remaining is None

    def test_patch_active_row_credentials_resets_singleton_and_restarts(self, api: Client) -> None:
        row = _connected_app(is_active=True)

        with (
            patch("apps.xero.api._restart_sibling_workers") as mock_restart,
            patch("apps.xero.api.xero_auth._reset_api_client") as mock_reset,
        ):
            api.patch(self._url(row), data={"client_secret": "s2"}, content_type="application/json")

        mock_restart.assert_called_once()
        mock_reset.assert_called_once()

    def test_patch_inactive_row_credentials_does_not_restart(self, api: Client) -> None:
        row = _connected_app(is_active=False)

        with patch("apps.xero.api._restart_sibling_workers") as mock_restart:
            api.patch(self._url(row), data={"client_secret": "s2"}, content_type="application/json")

        mock_restart.assert_not_called()

    def test_patch_label_only_does_not_restart(self, api: Client) -> None:
        row = _connected_app(is_active=True)

        with patch("apps.xero.api._restart_sibling_workers") as mock_restart:
            api.patch(self._url(row), data={"label": "L2"}, content_type="application/json")

        mock_restart.assert_not_called()

    def test_patch_duplicate_client_id_returns_400(self, api: Client) -> None:
        make_xero_app(client_id="c-taken")
        row = make_xero_app(client_id="c-mine")

        response = api.patch(
            self._url(row), data={"client_id": "c-taken"}, content_type="application/json"
        )

        assert response.status_code == 400


class TestXeroAppsDelete:
    def test_delete_inactive_row_succeeds(self, api: Client) -> None:
        row = make_xero_app(client_id="c-b", is_active=False)

        response = api.delete(f"{APPS_URL}{row.id}/")

        assert response.status_code == 204
        assert not XeroApp.objects.filter(id=row.id).exists()

    def test_delete_active_row_refused(self, api: Client) -> None:
        row = make_xero_app(client_id="c-a", is_active=True)

        response = api.delete(f"{APPS_URL}{row.id}/")

        assert response.status_code == 400
        assert XeroApp.objects.filter(id=row.id).exists()


class TestXeroAppsActivate:
    def test_activate_swaps(self, api: Client) -> None:
        a = make_xero_app(client_id="c-a", is_active=True)
        b = make_xero_app(client_id="c-b", is_active=False)

        with patch("apps.xero.active_app._restart_sibling_workers"):
            response = api.post(f"{APPS_URL}{b.id}/activate/")

        assert response.status_code == 200
        body = response.json()
        assert body["is_active"] is True
        assert body["restart_initiated"] is True
        a.refresh_from_db()
        assert not a.is_active

    def test_activate_unknown_id_404(self, api: Client) -> None:
        response = api.post(f"{APPS_URL}{uuid.uuid4()}/activate/")

        assert response.status_code == 404


class TestXeroAppsConfig:
    def test_config_returns_day_floor(self, api: Client) -> None:
        floor = CompanyDefaults.get_solo().xero_automated_day_floor

        response = api.get(f"{APPS_URL}config/")

        assert response.status_code == 200
        assert response.json() == {"day_floor": floor}
