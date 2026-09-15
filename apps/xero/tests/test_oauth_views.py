"""The browser OAuth flow: auth guard, state binding, error landing.

Business risk covered: these are the only anonymous-reachable views that can
overwrite the active XeroApp's tokens. The state check is what stops a foreign
callback from rebinding the install's Xero connection (v1 stored the state and
never compared it), and every failure must land on the SPA with ``xero_error``
— an operator staring at a Django 500 page mid-OAuth cannot recover.

The state lives in the shared cache, not the session: an instance alias starts
the flow on one hostname and Xero returns to the canonical one, where the
alias's session cookie never arrives. The flow must land the browser back on
the hostname it started from.
"""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.cache import caches
from django.test import Client, override_settings

from apps.xero.constants import OAUTH_STATE_TTL_SECONDS, oauth_state_key

from .conftest import make_xero_app

pytestmark = pytest.mark.django_db

AUTHENTICATE_URL = "/api/xero/authenticate/"
CALLBACK_URL = "/api/xero/oauth/callback/"
ALIAS_HOST = "uat-office.example.test"


@pytest.fixture(autouse=True)
def _empty_shared_cache() -> None:
    # locmem persists across tests within a worker; a state armed by one test
    # must not satisfy another's callback.
    caches["shared"].clear()


def _arm_state(
    state: str = "expected-state", return_to: str = "http://testserver/admin/company/xero"
) -> None:
    caches["shared"].set(oauth_state_key(state), return_to, OAUTH_STATE_TTL_SECONDS)


class TestXeroAuthenticate:
    def test_anonymous_is_forbidden(self, client: Client) -> None:
        make_xero_app(client_id="c-a", is_active=True)

        response = client.get(AUTHENTICATE_URL)

        assert response.status_code == 403

    def test_non_office_staff_is_forbidden(self, non_office_api: Client) -> None:
        make_xero_app(client_id="c-a", is_active=True)

        response = non_office_api.get(AUTHENTICATE_URL)

        assert response.status_code == 403

    def test_redirects_to_consent_with_state_in_shared_cache(self, api: Client) -> None:
        make_xero_app(client_id="c-a", is_active=True, redirect_uri="https://example.test/cb")

        response = api.get(AUTHENTICATE_URL, {"next": "/admin/company/xero"})

        assert response.status_code == 302
        parsed = urlparse(response["Location"])
        assert parsed.hostname == "login.xero.com"
        params = parse_qs(parsed.query)
        assert params["client_id"] == ["c-a"]
        # Always the registered URI, whatever host the flow started on.
        assert params["redirect_uri"] == ["https://example.test/cb"]
        # The state in the URL is the one the callback will demand back, and it
        # carries the absolute address to return the browser to.
        [state] = params["state"]
        assert (
            caches["shared"].get(oauth_state_key(state)) == "http://testserver/admin/company/xero"
        )

    @override_settings(ALLOWED_HOSTS=["testserver", ALIAS_HOST])
    def test_started_on_an_alias_returns_to_the_alias(self, api: Client) -> None:
        """The alias has no Xero redirect URI of its own; the return address is what carries it."""
        make_xero_app(client_id="c-a", is_active=True, redirect_uri="https://example.test/cb")

        response = api.get(AUTHENTICATE_URL, {"next": "/admin/company/xero"}, HTTP_HOST=ALIAS_HOST)

        assert response.status_code == 302
        params = parse_qs(urlparse(response["Location"]).query)
        assert params["redirect_uri"] == ["https://example.test/cb"]
        [state] = params["state"]
        assert (
            caches["shared"].get(oauth_state_key(state))
            == f"http://{ALIAS_HOST}/admin/company/xero"
        )

    def test_scheme_relative_next_is_refused(self, api: Client) -> None:
        """``//evil`` joined to the request origin would resolve to ``https://evil``."""
        make_xero_app(client_id="c-a", is_active=True)

        response = api.get(AUTHENTICATE_URL, {"next": "//evil.test/x"})

        assert response.status_code == 400


class TestXeroOauthCallback:
    def test_denied_consent_lands_on_spa_with_error(self, client: Client) -> None:
        _arm_state()

        response = client.get(
            CALLBACK_URL,
            {
                "error": "access_denied",
                "error_description": "User declined",
                "state": "expected-state",
            },
        )

        assert response.status_code == 302
        assert response["Location"].startswith("http://testserver/admin/company/xero?")
        assert "xero_error=User+declined" in response["Location"]

    def test_missing_code_lands_on_spa_with_error(self, client: Client) -> None:
        _arm_state()

        response = client.get(CALLBACK_URL, {"state": "expected-state"})

        assert response.status_code == 302
        assert "xero_error=" in response["Location"]

    def test_unknown_state_refuses_the_code_exchange(self, client: Client) -> None:
        """The CSRF check v1 never performed: a foreign state must not bind."""
        _arm_state(state="expected-state")

        with patch("apps.xero.oauth_views.exchange_code_for_token") as mock_exchange:
            response = client.get(CALLBACK_URL, {"code": "attacker-code", "state": "forged-state"})

        mock_exchange.assert_not_called()
        assert response.status_code == 302
        # No return address for a state nobody minted: land on this host's root.
        assert response["Location"].startswith("http://testserver/?")
        assert "xero_error=" in response["Location"]

    def test_direct_hit_without_state_refuses_the_code_exchange(self, client: Client) -> None:
        with patch("apps.xero.oauth_views.exchange_code_for_token") as mock_exchange:
            response = client.get(CALLBACK_URL, {"code": "code"})

        mock_exchange.assert_not_called()
        assert response.status_code == 302
        assert "xero_error=" in response["Location"]

    def test_happy_path_exchanges_and_lands_where_the_flow_started(self, client: Client) -> None:
        _arm_state(return_to=f"https://{ALIAS_HOST}/admin/company/xero")

        with (
            patch(
                "apps.xero.oauth_views.exchange_code_for_token",
                return_value={"access_token": "AT"},
            ) as mock_exchange,
            patch("apps.xero.oauth_views.get_api_client") as mock_client,
            patch("apps.xero.oauth_views.IdentityApi") as mock_identity,
        ):
            response = client.get(CALLBACK_URL, {"code": "good-code", "state": "expected-state"})

        mock_client.assert_called_once()
        mock_exchange.assert_called_once_with("good-code")
        mock_identity.assert_called_once()
        assert response.status_code == 302
        assert response["Location"] == f"https://{ALIAS_HOST}/admin/company/xero"
        # The state is single-use: a replayed callback must not pass again.
        assert caches["shared"].get(oauth_state_key("expected-state")) is None

    def test_replayed_callback_is_refused(self, client: Client) -> None:
        _arm_state()
        with (
            patch(
                "apps.xero.oauth_views.exchange_code_for_token", return_value={"access_token": "AT"}
            ),
            patch("apps.xero.oauth_views.get_api_client"),
            patch("apps.xero.oauth_views.IdentityApi"),
        ):
            client.get(CALLBACK_URL, {"code": "good-code", "state": "expected-state"})

        with patch("apps.xero.oauth_views.exchange_code_for_token") as mock_exchange:
            response = client.get(CALLBACK_URL, {"code": "good-code", "state": "expected-state"})

        mock_exchange.assert_not_called()
        assert "xero_error=" in response["Location"]

    def test_exchange_failure_lands_on_spa_not_a_500(self, client: Client) -> None:
        _arm_state()

        with patch(
            "apps.xero.oauth_views.exchange_code_for_token",
            side_effect=RuntimeError("Xero said 400"),
        ):
            response = client.get(CALLBACK_URL, {"code": "expired-code", "state": "expected-state"})

        assert response.status_code == 302
        assert response["Location"].startswith("http://testserver/admin/company/xero?")
        assert "xero_error=" in response["Location"]

    def test_xero_reported_error_in_exchange_result_lands_on_spa(self, client: Client) -> None:
        _arm_state()

        with patch(
            "apps.xero.oauth_views.exchange_code_for_token",
            return_value={"error": "invalid_grant"},
        ):
            response = client.get(CALLBACK_URL, {"code": "code", "state": "expected-state"})

        assert response.status_code == 302
        assert "xero_error=invalid_grant" in response["Location"]
