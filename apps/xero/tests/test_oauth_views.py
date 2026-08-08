"""The browser OAuth flow: auth guard, state binding, error landing.

Business risk covered: these are the only anonymous-reachable views that can
overwrite the active XeroApp's tokens. The state check is what stops a foreign
callback from rebinding the install's Xero connection (v1 stored the state and
never compared it), and every failure must land on the SPA with ``xero_error``
— an operator staring at a Django 500 page mid-OAuth cannot recover.
"""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client

from .conftest import make_xero_app

pytestmark = pytest.mark.django_db

AUTHENTICATE_URL = "/api/xero/authenticate/"
CALLBACK_URL = "/api/xero/oauth/callback/"


class TestXeroAuthenticate:
    def test_anonymous_is_forbidden(self, client: Client) -> None:
        make_xero_app(client_id="c-a", is_active=True)

        response = client.get(AUTHENTICATE_URL)

        assert response.status_code == 403

    def test_non_office_staff_is_forbidden(self, non_office_api: Client) -> None:
        make_xero_app(client_id="c-a", is_active=True)

        response = non_office_api.get(AUTHENTICATE_URL)

        assert response.status_code == 403

    def test_redirects_to_consent_with_state_in_session(self, api: Client) -> None:
        make_xero_app(client_id="c-a", is_active=True, redirect_uri="https://example.test/cb")

        response = api.get(AUTHENTICATE_URL, {"next": "/admin/company/xero"})

        assert response.status_code == 302
        parsed = urlparse(response["Location"])
        assert parsed.hostname == "login.xero.com"
        params = parse_qs(parsed.query)
        assert params["client_id"] == ["c-a"]
        assert params["redirect_uri"] == ["https://example.test/cb"]
        # The state in the URL is the one the callback will demand back.
        assert params["state"] == [api.session["oauth_state"]]
        assert api.session["post_login_redirect"] == "/admin/company/xero"


class TestXeroOauthCallback:
    def _arm_session(self, client: Client, state: str = "expected-state") -> None:
        session = client.session
        session["oauth_state"] = state
        session["post_login_redirect"] = "/admin/company/xero"
        session.save()

    def test_denied_consent_lands_on_spa_with_error(self, api: Client) -> None:
        self._arm_session(api)

        response = api.get(
            CALLBACK_URL, {"error": "access_denied", "error_description": "User declined"}
        )

        assert response.status_code == 302
        assert "xero_error=User+declined" in response["Location"]

    def test_missing_code_lands_on_spa_with_error(self, api: Client) -> None:
        self._arm_session(api)

        response = api.get(CALLBACK_URL, {"state": "expected-state"})

        assert response.status_code == 302
        assert "xero_error=" in response["Location"]

    def test_state_mismatch_refuses_the_code_exchange(self, api: Client) -> None:
        """The CSRF check v1 never performed: a foreign state must not bind."""
        self._arm_session(api, state="expected-state")

        with patch("apps.xero.oauth_views.exchange_code_for_token") as mock_exchange:
            response = api.get(CALLBACK_URL, {"code": "attacker-code", "state": "forged-state"})

        mock_exchange.assert_not_called()
        assert response.status_code == 302
        assert "xero_error=" in response["Location"]

    def test_missing_session_state_refuses_the_code_exchange(self, api: Client) -> None:
        """A callback with no initiating session (direct hit) must not exchange."""
        with patch("apps.xero.oauth_views.exchange_code_for_token") as mock_exchange:
            response = api.get(CALLBACK_URL, {"code": "code", "state": "any"})

        mock_exchange.assert_not_called()
        assert response.status_code == 302
        assert "xero_error=" in response["Location"]

    def test_happy_path_exchanges_and_lands_on_spa(self, api: Client) -> None:
        self._arm_session(api)

        with (
            patch(
                "apps.xero.oauth_views.exchange_code_for_token",
                return_value={"access_token": "AT"},
            ) as mock_exchange,
            patch("apps.xero.oauth_views.get_api_client") as mock_client,
            patch("apps.xero.oauth_views.IdentityApi") as mock_identity,
        ):
            response = api.get(CALLBACK_URL, {"code": "good-code", "state": "expected-state"})

        mock_client.assert_called_once()

        mock_exchange.assert_called_once_with("good-code")
        mock_identity.assert_called_once()
        assert response.status_code == 302
        assert response["Location"].endswith("/admin/company/xero")
        # The state is single-use: a replayed callback must not pass again.
        assert "oauth_state" not in api.session

    def test_exchange_failure_lands_on_spa_not_a_500(self, api: Client) -> None:
        self._arm_session(api)

        with patch(
            "apps.xero.oauth_views.exchange_code_for_token",
            side_effect=RuntimeError("Xero said 400"),
        ):
            response = api.get(CALLBACK_URL, {"code": "expired-code", "state": "expected-state"})

        assert response.status_code == 302
        assert "xero_error=" in response["Location"]

    def test_xero_reported_error_in_exchange_result_lands_on_spa(self, api: Client) -> None:
        self._arm_session(api)

        with patch(
            "apps.xero.oauth_views.exchange_code_for_token",
            return_value={"error": "invalid_grant"},
        ):
            response = api.get(CALLBACK_URL, {"code": "code", "state": "expected-state"})

        assert response.status_code == 302
        assert "xero_error=invalid_grant" in response["Location"]
