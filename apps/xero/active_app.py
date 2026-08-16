"""Active-app resolution and swap.

Public surface:
- ``get_active_app()`` — load the row with ``is_active=True``.
- ``swap_active(app_id)`` — atomically flip the active row, invalidate the
  in-process ApiClient singleton, and restart sibling worker units so their
  fresh processes rebuild against the new row.
- ``wipe_tokens_and_quota(app)`` — null all token/quota fields on a row.

The ApiClient itself lives in ``apps.xero.auth`` as a lazy process singleton
(``auth.api_client``). Swap propagation across worker processes happens via
systemd restart, not a per-call DB lookup.
"""

import logging
import os
import subprocess
import uuid

from django.db import transaction

from apps.core.errors import persist_app_error
from apps.xero.constants import TENANT_ID_CACHE_KEY, tenant_cache
from apps.xero.models import XeroApp

logger = logging.getLogger(__name__)


class NoActiveXeroAppError(Exception):
    """Raised when no XeroApp row has is_active=True."""


def get_active_app() -> XeroApp:
    """Load the XeroApp row marked is_active=True."""
    try:
        return XeroApp.objects.get(is_active=True)
    except XeroApp.DoesNotExist as exc:
        raise NoActiveXeroAppError("No XeroApp marked is_active=True") from exc


def swap_active(app_id: uuid.UUID) -> XeroApp:
    """Atomically clear is_active on every other row and set it on the target.

    After the DB flip, invalidate the calling process's cached ApiClient so
    its next Xero call rebuilds against the new row. Then dispatch a detached
    ``systemctl restart`` for the sibling units (gunicorn / scheduler /
    celery-worker) so they rebuild their own singletons. The restart is
    detached (``Popen`` with ``start_new_session=True``) because if we're
    running inside the gunicorn unit we'd otherwise SIGKILL ourselves before
    the HTTP response goes out.
    """
    with transaction.atomic():
        target = XeroApp.objects.select_for_update().get(id=app_id)
        if target.is_active:
            return target
        XeroApp.objects.filter(is_active=True).update(is_active=False)
        target.is_active = True
        target.save(update_fields=["is_active", "updated_at"])

    tenant_cache().delete(TENANT_ID_CACHE_KEY)

    # Invalidate this process's singleton.
    # Call-time import: auth imports active_app inside _build(), so a
    # top-level import here would be circular.
    from apps.xero import auth  # noqa: PLC0415

    auth._reset_api_client()

    _restart_sibling_workers()

    logger.info("Active XeroApp swapped to %s (%s)", target.id, target.label)
    return target


def _restart_sibling_workers() -> None:
    """Detached ``sudo systemctl restart`` of the per-instance worker units.

    Reads ``INSTANCE`` (the systemd-unit naming slug, e.g. ``msm-prod``),
    NOT ``DB_NAME`` (which uses underscores, e.g. ``dw_msm_prod`` — wrong
    shape for unit names). The two diverged in instance.sh: see
    ``scripts/server/common.sh:instance_user`` and the unit templates.

    No-op when ``INSTANCE`` is unset (dev/test): the in-process singleton
    has already been invalidated; user-owned VS Code services stay stale
    until the user restarts them, per the dev-services policy.
    """
    instance = os.getenv("INSTANCE")
    if not instance:
        logger.info("No INSTANCE env; skipping worker restart (dev/test).")
        return

    units: list[str] = [
        f"gunicorn-{instance}.service",
        f"celery-beat-{instance}.service",
        f"celery-worker-{instance}.service",
    ]
    try:
        subprocess.Popen(  # noqa: S603 -- fixed argv; unit names derive from INSTANCE env set by the deploy
            ["sudo", "systemctl", "restart", *units],  # noqa: S607 -- sudo/systemctl resolve via PATH on the servers by design
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Dispatched detached restart for: %s", ", ".join(units))
    except Exception as exc:
        persist_app_error(exc)
        raise


def wipe_tokens_and_quota(app: XeroApp) -> None:
    """Null all token + quota fields on the row.

    Used when credentials change (a new client_id is a different Xero app
    from Xero's perspective; old tokens and quota state are invalid).
    """
    XeroApp.objects.filter(id=app.id).update(
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
    tenant_cache().delete(TENANT_ID_CACHE_KEY)
