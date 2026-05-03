"""Active-app resolution and per-app ApiClient construction.

This is the only place that asks "which XeroApp is active?" and the only
place that builds an xero-python ApiClient. Every Xero call site goes
through ``get_active_client()``, which holds a process-level cache and
rebuilds whenever the active row's id changes — so swapping the active
row in the DB causes the next call in every Django/Celery/scheduler
process to rebuild against the new credentials. No restart needed.

Token-saver and quota-writer paths write to the row whose credentials
made the call (passed explicitly as app_id), NOT to whichever row is
active at the moment of write. This keeps a swap racing an in-flight
refresh safe: the in-flight call finishes against its own row, the new
active row is untouched.
"""

import logging
from typing import Optional, Tuple
from uuid import UUID

from django.core.cache import cache
from django.db import transaction
from xero_python.api_client import ApiClient, Configuration
from xero_python.api_client.oauth2 import OAuth2Token

from apps.workflow.api.xero.client import RateLimitedRESTClient
from apps.workflow.api.xero.constants import TENANT_ID_CACHE_KEY
from apps.workflow.models import XeroApp

logger = logging.getLogger("xero")

_client_cache: Tuple[Optional[UUID], Optional[ApiClient]] = (None, None)


class NoActiveXeroApp(Exception):
    """Raised when no XeroApp row has is_active=True."""


def get_active_app() -> XeroApp:
    try:
        return XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist as exc:
        raise NoActiveXeroApp("No XeroApp marked is_active=True") from exc


def swap_active(app_id) -> XeroApp:
    """Atomically clear is_active on every other row and set it on the target."""
    with transaction.atomic():
        target = XeroApp.objects.select_for_update().get(id=app_id)
        if target.is_active:
            return target
        XeroApp.objects.filter(is_active=True).update(is_active=False)
        target.is_active = True
        target.save(update_fields=["is_active", "updated_at"])
    _reset_client_cache()
    # Tenant id was cached against the previous app's credentials. Without
    # this delete, the next get_tenant_id() returns the prior tenant and
    # subsequent calls hit the wrong tenant under the new credentials.
    cache.delete(TENANT_ID_CACHE_KEY)
    logger.info(f"Active XeroApp swapped to {target.id} ({target.label})")
    return target


def wipe_tokens_and_quota(app: XeroApp) -> None:
    """Null all token + quota fields on the row.

    Used when credentials change (a new client_id is a different Xero app
    from Xero's perspective; old tokens and quota state are invalid).
    """
    XeroApp.objects.filter(id=app.id).update(
        tenant_id=None,
        token_type=None,
        access_token=None,
        refresh_token=None,
        expires_at=None,
        scope=None,
        day_remaining=None,
        minute_remaining=None,
        snapshot_at=None,
        last_429_at=None,
    )
    # If this row is currently active, the cached tenant id was derived
    # from the now-wiped credentials and is no longer authoritative. Clear
    # it unconditionally — the cache key is global, not per-app, so the
    # safe move is to drop it whenever any row's credentials change.
    cache.delete(TENANT_ID_CACHE_KEY)


def build_api_client(app: XeroApp) -> ApiClient:
    """Construct an ApiClient bound to the given app's credentials and id."""
    api_client = ApiClient(
        Configuration(
            debug=False,
            oauth2_token=OAuth2Token(
                client_id=app.client_id,
                client_secret=app.client_secret,
            ),
        ),
    )
    api_client.rest_client = RateLimitedRESTClient(
        api_client.configuration, app_id=app.id
    )
    # Local import: auth.py imports from active_app for refresh.
    from apps.workflow.api.xero import auth

    auth.bind_token_callbacks(api_client, app.id)
    return api_client


def get_active_client() -> ApiClient:
    """Return a process-cached ApiClient for the currently active app.

    Rebuilds on first call after a swap_active(). One indexed PK read
    per call to detect the swap.
    """
    global _client_cache
    active = get_active_app()
    cached_id, cached_client = _client_cache
    if cached_id == active.id and cached_client is not None:
        return cached_client
    client = build_api_client(active)
    _client_cache = (active.id, client)
    return client


def _reset_client_cache() -> None:
    """Test hook + post-swap invalidation."""
    global _client_cache
    _client_cache = (None, None)
