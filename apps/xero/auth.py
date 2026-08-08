"""Xero OAuth2 helpers — backed by the XeroApp table.

Module-level ``api_client`` is a process singleton built lazily from the
active XeroApp row on first attribute access. Token-saver and quota-writer
callbacks bound at construction time target the row whose credentials built
the client, so an in-flight refresh during a swap window writes to its own
row, not the new active row.

Active-row swaps must call ``_reset_api_client()`` to invalidate the
singleton in the calling process; ``swap_active`` also restarts the
other worker units so their fresh processes rebuild from the new row.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict
from urllib.parse import quote, urlencode

import requests
from django.core.cache import cache, caches
from xero_python.api_client import ApiClient, Configuration
from xero_python.api_client.oauth2 import OAuth2Token, TokenApi
from xero_python.identity import IdentityApi

from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.xero.client import RateLimitedRESTClient
from apps.xero.constants import TENANT_ID_CACHE_KEY, XERO_SCOPES
from apps.xero.models import XeroApp

logger = logging.getLogger(__name__)


class TokenPayload(TypedDict):
    """The OAuth token material stored on a XeroApp row, SDK-callback shaped.

    ``expires_at`` is a POSIX timestamp (the SDK's convention), not a
    datetime; ``scope`` is the split list, not the space-joined string the
    row stores.
    """

    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: float
    scope: list[str]
    expires_in: int


_api_client: ApiClient | None = None
REFRESH_LOCK_KEY = "xero_token_refresh_lock"
REFRESH_LOCK_TIMEOUT_SECONDS = 60
REFRESH_WINDOW = timedelta(seconds=60)
_shared_cache = caches["shared"]


def _build() -> ApiClient:
    """Construct an ApiClient bound to the currently active XeroApp row."""
    # Local import: active_app imports are cheap, but avoid pulling at
    # module-load time (auth.py is imported very early).
    from apps.xero.active_app import get_active_app  # noqa: PLC0415 -- see module comment above

    app = get_active_app()
    client = ApiClient(
        Configuration(
            debug=False,
            oauth2_token=OAuth2Token(
                client_id=app.client_id,
                client_secret=app.client_secret,
            ),
        ),
    )
    client.rest_client = RateLimitedRESTClient(client.configuration, app_id=app.id)
    bind_token_callbacks(client, app.id)
    return client


def _get_or_build() -> ApiClient:
    global _api_client  # noqa: PLW0603 -- the process singleton this module exists to hold
    if _api_client is None:
        _api_client = _build()
    return _api_client


class _ApiClientProxy:
    """Forwards attribute access to the lazy ApiClient singleton.

    Reason for the proxy (vs PEP 562 module ``__getattr__``): callsites do
    ``from auth import api_client`` which evaluates the name at the
    importer's import time. A PEP 562 ``__getattr__`` would fire ``_build()``
    at import — hitting the DB before any code wants Xero. The proxy is a
    real, cheap module attribute; ``_build()`` only fires when something
    reads/sets an attribute on it (i.e. an actual SDK call).
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_or_build(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(_get_or_build(), name, value)


api_client = _ApiClientProxy()


def get_api_client() -> ApiClient:
    """Return the process ApiClient, building it on first use.

    The typed accessor for v2 code: ``api_client`` (the proxy) exists for
    call sites porting v1's ``from auth import api_client`` shape, but its
    ``__getattr__`` forwarding is untyped — new code should take the real
    client from here instead.
    """
    return _get_or_build()


def _reset_api_client() -> None:
    """Invalidate the cached singleton. Called by ``swap_active`` and tests."""
    global _api_client  # noqa: PLW0603 -- the process singleton this module exists to hold
    _api_client = None


def _payload_from_row(app: XeroApp) -> TokenPayload | None:
    """Build an OAuth token payload from a XeroApp row."""
    if not app.access_token or not app.expires_at or not app.token_type:
        return None
    expires_in = int((app.expires_at - datetime.now(UTC)).total_seconds())
    return {
        "access_token": app.access_token,
        "refresh_token": app.refresh_token,
        "token_type": app.token_type,
        "expires_at": app.expires_at.timestamp(),
        "scope": (app.scope or "").split(),
        "expires_in": expires_in,
    }


def _make_token_getter(app_id: uuid.UUID) -> Callable[[], dict[str, Any] | None]:
    """Build a token-getter callback bound to a specific app row."""

    def _get() -> dict[str, Any] | None:
        try:
            app = XeroApp.objects.get(id=app_id)
        except XeroApp.DoesNotExist:
            return None
        payload = _payload_from_row(app)
        return dict(payload) if payload else None

    return _get


def _make_token_saver(app_id: uuid.UUID) -> Callable[[dict[str, Any]], None]:
    """Build a token-saver callback bound to a specific app row.

    The xero-python SDK calls oauth2_token_saver after a successful refresh;
    our callback writes the new tokens to the row whose id was captured
    here, NOT to whichever row is currently active. This is what makes
    credential swaps safe under concurrent refreshes.

    The saver writes token fields only. The active tenant lives on
    CompanyDefaults.xero_tenant_id and the global TENANT_ID_CACHE_KEY —
    resolved per call by get_tenant_id(), never stored on the app row.
    """

    def _save(token: dict[str, Any]) -> None:
        if not token.get("expires_in"):
            raise ValueError("Missing expires_in in Xero token response")
        expires_at = datetime.now(UTC) + timedelta(seconds=token["expires_in"])

        scope = token["scope"]
        scope_str = " ".join(scope) if isinstance(scope, list) else str(scope)

        update_fields: dict[str, Any] = {
            "access_token": str(token["access_token"]),
            "token_type": str(token["token_type"]),
            "expires_at": expires_at,
            "scope": scope_str,
        }
        refresh = token.get("refresh_token")
        if refresh:
            update_fields["refresh_token"] = str(refresh)

        try:
            XeroApp.objects.filter(id=app_id).update(**update_fields)
            logger.info("Stored token on XeroApp %s, expires %s", app_id, expires_at.isoformat())
        except Exception as exc:
            persist_app_error(exc)
            raise

    return _save


def bind_token_callbacks(client: ApiClient, app_id: uuid.UUID) -> None:
    """Wire the SDK's token getter/saver to the row identified by app_id."""
    client.oauth2_token_getter(_make_token_getter(app_id))
    client.oauth2_token_saver(_make_token_saver(app_id))


def refresh_token() -> TokenPayload | None:
    """Refresh the active row's token via Xero's TokenApi.

    Returns the payload re-read from the row after the refresh was persisted
    (v1 returned the raw SDK response dict; re-reading returns exactly what
    was stored, and gives the callback-written ``expires_at`` its canonical
    row-datetime form).
    """
    try:
        app = XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist:
        logger.debug("No active XeroApp row; cannot refresh")
        return None
    payload = _payload_from_row(app)
    if not payload or not payload["refresh_token"]:
        logger.debug("Active row has no refresh_token to refresh")
        return None

    try:
        token_api = TokenApi(
            _get_or_build(),
            client_id=app.client_id,
            client_secret=app.client_secret,
        )
        refreshed = token_api.refresh_token(payload["refresh_token"], payload["scope"])
        if isinstance(refreshed.get("scope"), str):
            refreshed["scope"] = refreshed["scope"].split()
        # TokenApi.refresh_token is the low-level POST — it returns the new
        # tokens but does NOT invoke the bound oauth2_token_saver. Persist
        # explicitly via set_oauth2_token, which calls the saver.
        _get_or_build().set_oauth2_token(refreshed)
    except Exception as exc:
        persist_app_error(exc)
        raise

    app.refresh_from_db()
    return _payload_from_row(app)


def _payload_needs_refresh(payload: TokenPayload) -> bool:
    expires_at_dt = datetime.fromtimestamp(payload["expires_at"], tz=UTC)
    return datetime.now(UTC) > expires_at_dt - REFRESH_WINDOW


def get_valid_token() -> TokenPayload | None:  # noqa: PLR0911 -- a guard ladder: each return is one distinct not-connected case
    """Return a valid token, refreshing if possible when near expiry.

    ``None`` means the installation is not connected, or the active row lacks
    the stored token material required to refresh. Refresh attempts that reach
    Xero and fail propagate to the caller so callers do not
    mistake operational failures for an unconnected install.
    """
    try:
        app = XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist:
        return None

    payload = _payload_from_row(app)
    if not payload:
        return None
    if not _payload_needs_refresh(payload):
        return payload

    if not payload["refresh_token"]:
        logger.debug("Active XeroApp row needs refresh but has no refresh_token")
        return None

    lock_owner = f"{app.id}:{uuid.uuid4().hex}"
    if _shared_cache.add(
        REFRESH_LOCK_KEY,
        lock_owner,
        timeout=REFRESH_LOCK_TIMEOUT_SECONDS,
    ):
        try:
            return refresh_token()
        finally:
            if _shared_cache.get(REFRESH_LOCK_KEY) == lock_owner:
                _shared_cache.delete(REFRESH_LOCK_KEY)

    # Another process is refreshing the rotating Xero token. Re-read the row:
    # if it already wrote a fresh token, use it; otherwise report no valid
    # token instead of racing the same refresh_token.
    try:
        app.refresh_from_db()
    except XeroApp.DoesNotExist:
        return None
    payload = _payload_from_row(app)
    if not payload or _payload_needs_refresh(payload):
        return None
    return payload


def get_authentication_url(state: str) -> str:
    """Build the Xero consent URL using the active row's credentials."""
    try:
        app = XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist as exc:
        persist_app_error(exc)
        raise

    params = {
        "response_type": "code",
        "client_id": app.client_id,
        "redirect_uri": app.redirect_uri,
        "scope": " ".join(XERO_SCOPES),
        "state": state,
    }
    logger.info("Generating Xero consent URL for client %s", app.client_id[:8])
    return f"https://login.xero.com/identity/connect/authorize?{urlencode(params, quote_via=quote)}"


def get_tenant_id_from_connections() -> str:
    """Get tenant ID using the active client."""
    identity_api = IdentityApi(_get_or_build())
    connections = identity_api.get_connections()
    if not connections:
        raise RuntimeError("No Xero tenants found.")

    company_defaults = CompanyDefaults.get_solo()
    if not company_defaults.xero_tenant_id:
        raise RuntimeError(
            "No Xero tenant ID configured in company defaults. Please set this up first."
        )

    available = [conn.tenant_id for conn in connections]
    if company_defaults.xero_tenant_id not in available:
        raise RuntimeError(
            "Configured Xero tenant ID is no longer valid. "
            "Please check your company defaults configuration."
        )
    return company_defaults.xero_tenant_id


def exchange_code_for_token(code: str) -> dict[str, Any]:
    """Exchange the authorization code for tokens at Xero's token endpoint.

    Uses the active row's credentials and writes the resulting tokens onto
    that same row. State validation happens in the callback view BEFORE this
    is called — v1 threaded state/session_state in here and then only logged
    them, which is how the check went missing.
    """
    try:
        app = XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist as exc:
        persist_app_error(exc)
        raise

    # The authorization code is single-use but still a credential until
    # exchanged — never logged.
    logger.debug("Exchanging Xero authorization code for tokens")
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
        response = requests.post(url, headers=headers, data=data, timeout=30)
        response.raise_for_status()
        token: dict[str, Any] = response.json()
        if isinstance(token.get("scope"), str):
            token["scope"] = token["scope"].split()
        # Write to the same row that issued the request.
        _make_token_saver(app.id)(token)
    except Exception as exc:
        persist_app_error(exc)
        raise
    return token


def get_tenant_id() -> str:
    """Return the active Xero tenant ID (cached in TENANT_ID_CACHE_KEY).

    Source of truth is CompanyDefaults.xero_tenant_id; the cache only avoids
    re-reading it. An unset value is a configuration error, not a fallback case.
    """
    tenant_id = cache.get(TENANT_ID_CACHE_KEY)

    payload = get_valid_token()
    if not payload:
        raise RuntimeError("No valid Xero token found. Please complete the authorization workflow.")

    if tenant_id:
        logger.debug("Xero tenant ID resolved from cache")
        return str(tenant_id)

    company_defaults = CompanyDefaults.get_solo()
    if not company_defaults.xero_tenant_id:
        exc = RuntimeError(
            "No Xero tenant ID configured in company defaults. Please set this up first."
        )
        persist_app_error(exc)
        raise exc

    resolved: str = company_defaults.xero_tenant_id
    cache.set(TENANT_ID_CACHE_KEY, resolved)
    logger.info("Xero tenant ID resolved from CompanyDefaults and cached")
    return resolved
