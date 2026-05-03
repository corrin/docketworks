"""Xero OAuth2 helpers — backed by the XeroApp table.

Every public function operates against the active XeroApp row (the one
with is_active=True). Token-saver callbacks bound at client-construction
time target a specific app_id, so background refreshes never clobber
another row's tokens during a swap race.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote, urlencode

import requests
from django.core.cache import cache
from xero_python.api_client import ApiClient
from xero_python.api_client.oauth2 import TokenApi
from xero_python.identity import IdentityApi

from apps.workflow.api.xero.constants import TENANT_ID_CACHE_KEY, XERO_SCOPES
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults, XeroApp
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("xero")


def _payload_from_row(app: XeroApp) -> Optional[Dict[str, Any]]:
    """Build an OAuth token payload from a XeroApp row."""
    if not app.access_token or not app.expires_at:
        return None
    expires_in = int((app.expires_at - datetime.now(timezone.utc)).total_seconds())
    return {
        "access_token": app.access_token,
        "refresh_token": app.refresh_token,
        "token_type": app.token_type,
        "expires_at": app.expires_at.timestamp(),
        "scope": (app.scope or "").split(),
        "expires_in": expires_in,
    }


def get_token() -> Optional[Dict[str, Any]]:
    """Return the active row's token payload, or None if absent/expired."""
    try:
        app = XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist:
        return None
    payload = _payload_from_row(app)
    if not payload or payload["expires_in"] <= 0:
        return None
    return payload


def _make_token_getter(app_id) -> Callable[[], Optional[Dict[str, Any]]]:
    """Build a token-getter callback bound to a specific app row."""

    def _get() -> Optional[Dict[str, Any]]:
        try:
            app = XeroApp.objects.get(id=app_id)
        except XeroApp.DoesNotExist:
            return None
        return _payload_from_row(app)

    return _get


def _make_token_saver(app_id) -> Callable[[Dict[str, Any]], None]:
    """Build a token-saver callback bound to a specific app row.

    The xero-python SDK calls oauth2_token_saver after a successful refresh;
    our callback writes the new tokens to the row whose id was captured
    here, NOT to whichever row is currently active. This is what makes
    credential swaps safe under concurrent refreshes.
    """

    def _save(token: Dict[str, Any]) -> None:
        if not token.get("expires_in"):
            raise ValueError("Missing expires_in in Xero token response")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token["expires_in"])

        # Tenant id may be None if the connections call fails; that's OK.
        tenant_id = None
        try:
            tenant_id = get_tenant_id_from_connections()
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_app_error(exc)
            logger.warning(f"Could not fetch tenant ID when storing token: {exc}")
            # Don't re-raise — we still want to persist the new tokens.

        scope = token["scope"]
        scope_str = " ".join(scope) if isinstance(scope, list) else str(scope)

        update_fields = {
            "access_token": str(token["access_token"]),
            "token_type": str(token["token_type"]),
            "expires_at": expires_at,
            "scope": scope_str,
        }
        refresh = token.get("refresh_token")
        if refresh:
            update_fields["refresh_token"] = str(refresh)
        if tenant_id:
            update_fields["tenant_id"] = tenant_id

        try:
            XeroApp.objects.filter(id=app_id).update(**update_fields)
            logger.info(
                f"Stored token on XeroApp {app_id}, expires {expires_at.isoformat()}"
            )
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc

    return _save


def bind_token_callbacks(api_client: ApiClient, app_id) -> None:
    """Wire the SDK's token getter/saver to the row identified by app_id."""
    api_client.oauth2_token_getter(_make_token_getter(app_id))
    api_client.oauth2_token_saver(_make_token_saver(app_id))


def refresh_token() -> Optional[Dict[str, Any]]:
    """Refresh the active row's token via Xero's TokenApi."""
    try:
        app = XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist:
        logger.debug("No active XeroApp row; cannot refresh")
        return None
    payload = _payload_from_row(app)
    if not payload or not payload.get("refresh_token"):
        logger.debug("Active row has no refresh_token to refresh")
        return None

    try:
        # Local import: avoid circular (active_app imports auth).
        from apps.workflow.api.xero.active_app import get_active_client

        api_client = get_active_client()
        token_api = TokenApi(
            api_client,
            client_id=app.client_id,
            client_secret=app.client_secret,
        )
        refreshed = token_api.refresh_token(payload["refresh_token"], payload["scope"])
        if isinstance(refreshed.get("scope"), str):
            refreshed["scope"] = refreshed["scope"].split()
        # The SDK invokes the bound saver as a side-effect — no explicit save.
        return refreshed
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        err = persist_app_error(exc)
        raise AlreadyLoggedException(exc, err.id) from exc


def get_valid_token() -> Optional[Dict[str, Any]]:
    """Return a valid token, refreshing if it expires within 5 minutes."""
    payload = get_token()
    if not payload:
        return None
    expires_at = payload.get("expires_at")
    if expires_at:
        expires_at_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        if datetime.now(timezone.utc) > expires_at_dt - timedelta(minutes=5):
            try:
                payload = refresh_token()
            except AlreadyLoggedException:
                return None
    return payload


def get_authentication_url(state: str) -> str:
    """Build the Xero consent URL using the active row's credentials."""
    try:
        app = XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist as exc:
        err = persist_app_error(exc)
        raise AlreadyLoggedException(exc, err.id) from exc

    params = {
        "response_type": "code",
        "client_id": app.client_id,
        "redirect_uri": app.redirect_uri,
        "scope": " ".join(XERO_SCOPES),
        "state": state,
    }
    logger.info(
        f"Generating authentication URL with params: \n{json.dumps(params, indent=2, sort_keys=True)}"
    )
    return f"https://login.xero.com/identity/connect/authorize?{urlencode(params, quote_via=quote)}"


def get_tenant_id_from_connections() -> str:
    """Get tenant ID using the active client."""
    from apps.workflow.api.xero.active_app import get_active_client

    api_client = get_active_client()
    identity_api = IdentityApi(api_client)
    connections = identity_api.get_connections()
    if not connections:
        raise Exception("No Xero tenants found.")

    company_defaults = CompanyDefaults.get_solo()
    if not company_defaults.xero_tenant_id:
        raise Exception(
            "No Xero tenant ID configured in company defaults. "
            "Please set this up first."
        )

    available = [conn.tenant_id for conn in connections]
    if company_defaults.xero_tenant_id not in available:
        raise Exception(
            "Configured Xero tenant ID is no longer valid. "
            "Please check your company defaults configuration."
        )
    return company_defaults.xero_tenant_id


def exchange_code_for_token(
    code: str, state: str, session_state: str
) -> Dict[str, Any]:
    """Exchange the authorization code at Xero's token endpoint using the
    active row's credentials, then write the resulting tokens onto that row.
    """
    try:
        app = XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist as exc:
        err = persist_app_error(exc)
        raise AlreadyLoggedException(exc, err.id) from exc

    logger.debug(
        f"Exchanging code for token. Code: {code}, State: {state}, "
        f"Session State: {session_state}"
    )
    url = "https://identity.xero.com/connect/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": app.redirect_uri,
        "client_id": app.client_id,
        "client_secret": app.client_secret,
    }

    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        token = response.json()
        if isinstance(token.get("scope"), str):
            token["scope"] = token["scope"].split()
        # Write to the same row that issued the request.
        _make_token_saver(app.id)(token)
        return token
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        err = persist_app_error(exc)
        raise AlreadyLoggedException(exc, err.id) from exc


def get_tenant_id() -> str:
    """Retrieve the tenant ID, refreshing the token or fetching from Xero
    connections if needed."""
    tenant_id = cache.get(TENANT_ID_CACHE_KEY)

    payload = get_valid_token()
    if not payload:
        raise Exception(
            "No valid Xero token found. Please complete the authorization workflow."
        )

    if not tenant_id:
        try:
            tenant_id = get_tenant_id_from_connections()
            cache.set(TENANT_ID_CACHE_KEY, tenant_id)
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc

    return tenant_id
