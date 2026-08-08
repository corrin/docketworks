"""Xero router: connection status, OAuth-adjacent operations, app management.

Mounted under ``/api/`` with paths carrying their own ``/xero/`` prefix. v1
served this from an app called ``workflow`` that v2 does not have; no external
party holds these URLs (the browser-redirect OAuth pair, which IS externally
held, lives in ``apps/xero/oauth_views.py`` outside ninja), so the paths and
operation ids follow v2 convention.

The ping payload's exact keys — ``connected`` / ``xero_readonly`` /
``xero_production_client`` — are a contract with the E2E harness preflight,
which fails closed on a missing ``xero_readonly``.
"""

import logging
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Model
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.responses import Status

from apps.accounting.registry import get_provider
from apps.core.auth import CookieJWTAuth, OfficeStaffCookieJWTAuth
from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.core.schemas import NonBlankText, ResponseSchema, omittable
from apps.xero import auth as xero_auth
from apps.xero.active_app import (
    NoActiveXeroAppError,
    _restart_sibling_workers,
    get_active_app,
    swap_active,
    wipe_tokens_and_quota,
)
from apps.xero.auth import get_valid_token
from apps.xero.constants import TENANT_ID_CACHE_KEY
from apps.xero.models import XeroApp, XeroPayItem
from apps.xero.sync_service import XeroSyncService

logger = logging.getLogger(__name__)

router = Router(tags=["xero"])
auth = CookieJWTAuth()
office_auth = OfficeStaffCookieJWTAuth()


class XeroPayItemOut(Schema):
    """A Xero leave type or earnings rate.

    ``multiplier`` is null for leave types and set for earnings rates — that is
    the discriminator the timesheet UI reads, alongside ``uses_leave_api``.
    """

    id: UUID
    xero_id: str | None
    xero_tenant_id: str | None
    name: str
    uses_leave_api: bool
    # float, not Decimal: v1's client is typed `z.number()`, and a Decimal
    # would serialise as a JSON string and fail that validation in the SPA.
    multiplier: float | None
    xero_last_modified: datetime | None
    xero_last_synced: datetime | None
    created_at: datetime
    updated_at: datetime


@router.get(
    "/xero/pay-items/",
    auth=auth,
    operation_id="xero_pay_items_list",
    response=list[XeroPayItemOut],
    summary="List Xero pay items (earnings rates and leave types)",
    tags=["xero"],
)
def xero_pay_items_list(request: HttpRequest) -> list[XeroPayItem]:
    """Every pay item, ordered leave-types-last then by name.

    A bare array rather than a paginated envelope: the table is a handful of
    rows a store loads once, and v1's client is typed for an array.
    """
    return list(XeroPayItem.objects.all())


# --- Connection status ---


class XeroPingOut(ResponseSchema):
    """Connection status plus the two safety flags the E2E preflight reads."""

    connected: bool
    xero_readonly: bool
    xero_production_client: bool


class XeroPingErrorOut(ResponseSchema):
    """Ping failure: the liveness check itself blew up (e.g. refresh failed)."""

    connected: bool
    error: str
    error_id: str


def _xero_production_client() -> bool:
    try:
        active = get_active_app()
    # deliberate-swallow: no active row means the install cannot be pointing at the
    # production client; False is the true answer, not a masked failure
    except NoActiveXeroAppError:
        return False
    production_client_ids = {
        client_id.strip().upper() for client_id in settings.PRODUCTION_XERO_CLIENT_IDS
    }
    return active.client_id.strip().upper() in production_client_ids


def _xero_ping_payload(*, connected: bool) -> XeroPingOut:
    return XeroPingOut(
        connected=connected,
        xero_readonly=settings.XERO_READONLY,
        xero_production_client=_xero_production_client(),
    )


@router.get(
    "/xero/ping/",
    auth=auth,
    operation_id="xero_ping_retrieve",
    response={200: XeroPingOut, 500: XeroPingErrorOut},
    summary="Check the Xero connection",
    tags=["xero"],
)
def xero_ping_retrieve(request: HttpRequest) -> Status[XeroPingOut | XeroPingErrorOut]:
    """Liveness check: ``connected`` means get_valid_token() produced a token.

    Not inert — a near-expiry token triggers a real refresh. A refresh that
    reaches Xero and fails is a 500 with an ``error_id``, never a quiet
    ``connected: false``: the E2E preflight and the header badge must not
    mistake an operational failure for a clean not-connected install.
    """
    try:
        token = get_valid_token()
    except Exception as exc:  # noqa: BLE001 -- persisted; the contract is a 500 payload with error_id, not a raise
        logger.error("Error in xero_ping: %s", exc)
        app_error = persist_app_error(exc)
        # Fixed message, not str(exc): refresh failures can quote upstream
        # responses and identifiers, and error_id already keys the operator
        # into the persisted detail.
        return Status(
            500,
            XeroPingErrorOut(
                connected=False,
                error="Xero connection check failed; see error_id.",
                error_id=str(app_error.id),
            ),
        )
    is_connected = bool(token)
    logger.info("Xero ping: connected=%s", is_connected)
    return Status(200, _xero_ping_payload(connected=is_connected))


@router.post(
    "/xero/disconnect/",
    auth=office_auth,
    operation_id="xero_disconnect_create",
    response=XeroPingOut,
    summary="Disconnect from Xero",
    tags=["xero"],
)
def xero_disconnect_create(request: HttpRequest) -> XeroPingOut:
    """Clear tokens on the active XeroApp.

    The row itself stays so the user can re-authorise without re-entering
    credentials. Inactive rows (e.g. a backup app) are untouched.
    """
    cache.delete(TENANT_ID_CACHE_KEY)
    try:
        active = get_active_app()
    # deliberate-swallow: disconnect on an install with no active app is already the
    # disconnected end-state the caller asked for
    except NoActiveXeroAppError:
        logger.info("xero_disconnect: no active XeroApp; nothing to do")
        return _xero_ping_payload(connected=False)
    wipe_tokens_and_quota(active)
    logger.info("Disconnected XeroApp %s (%s)", active.id, active.label)
    return _xero_ping_payload(connected=False)


# --- Branding themes ---


class XeroBrandingThemeOut(ResponseSchema):
    """A selectable Xero document theme."""

    external_id: str
    name: str
    is_default: bool


class XeroAuthRequiredOut(ResponseSchema):
    """The Xero connection is missing or unusable; the client should re-auth."""

    success: bool
    redirect_to_auth: bool
    message: str


@router.get(
    "/xero/branding-themes/",
    auth=office_auth,
    operation_id="xero_branding_themes_list",
    response={200: list[XeroBrandingThemeOut], 401: XeroAuthRequiredOut},
    summary="List Xero branding themes",
    tags=["xero"],
)
def xero_branding_themes_list(
    request: HttpRequest,
) -> Status[list[XeroBrandingThemeOut] | XeroAuthRequiredOut]:
    """Return the selectable document themes from the connected Xero organisation."""
    if not get_valid_token():
        return Status(
            401,
            XeroAuthRequiredOut(
                success=False,
                redirect_to_auth=True,
                message="Your Xero session has expired. Please log in again.",
            ),
        )
    themes = get_provider().list_document_themes()
    return Status(
        200,
        [
            XeroBrandingThemeOut(
                external_id=theme.external_id, name=theme.name, is_default=theme.is_default
            )
            for theme in themes
        ],
    )


# --- Sync trigger + status ---


class XeroSyncStartOut(ResponseSchema):
    """A dispatched sync run."""

    status: str
    message: str
    task_id: str | None


class XeroSyncInfoOut(ResponseSchema):
    """Last-sync times per entity plus whether a run is in flight."""

    last_syncs: dict[str, datetime | None]
    sync_range: str
    sync_in_progress: bool


@router.post(
    "/xero/sync/",
    auth=office_auth,
    operation_id="xero_sync_create",
    response={202: XeroSyncStartOut, 401: XeroAuthRequiredOut, 409: XeroSyncStartOut},
    summary="Start a Xero sync",
    tags=["xero"],
)
def xero_sync_create(request: HttpRequest) -> Status[XeroSyncStartOut | XeroAuthRequiredOut]:
    """Dispatch a background sync run.

    409 when a run already holds the lock (v1 said 200 "already running";
    the explicit status lets a client distinguish without parsing prose —
    the body still carries the active task id either way).
    """
    result = XeroSyncService.start_sync()
    if result.reason == "no_valid_token":
        return Status(
            401,
            XeroAuthRequiredOut(
                success=False,
                redirect_to_auth=True,
                message="No valid Xero token. Please authenticate.",
            ),
        )
    if result.reason == "already_running":
        return Status(
            409,
            XeroSyncStartOut(
                status="already_running",
                message="A sync is already running",
                task_id=result.task_id,
            ),
        )
    return Status(
        202,
        XeroSyncStartOut(status="started", message="Started new Xero sync", task_id=result.task_id),
    )


def _last_sync_time(model: type[Model]) -> datetime | None:
    # values_list, not attribute access: the entity models share this column
    # by convention, not by base class, and mypy rightly refuses the getattr.
    last_synced: datetime | None = (
        model._default_manager.order_by("-xero_last_synced")
        .values_list("xero_last_synced", flat=True)
        .first()
    )
    return last_synced


@router.get(
    "/xero/sync-info/",
    auth=office_auth,
    operation_id="xero_sync_info_retrieve",
    response=XeroSyncInfoOut,
    summary="Xero sync status and last-sync times",
    tags=["xero"],
)
def xero_sync_info_retrieve(request: HttpRequest) -> XeroSyncInfoOut:
    """Last-sync times for every entity and the in-progress flag.

    A pure read of local tables and the shared-cache lock. v1 gated this on
    get_valid_token(), which can perform a token refresh — a write on a GET
    for a payload that needs no token at all.
    """
    # Call-time import: the sync engine pulls the whole transform tree.
    from apps.xero.sync import ENTITY_CONFIGS  # noqa: PLC0415

    # pay_items leads because it is synced first in synchronise_xero_data —
    # the table mirrors that order to match the live log.
    last_syncs: dict[str, datetime | None] = {"pay_items": _last_sync_time(XeroPayItem)}
    for entity_key, config in ENTITY_CONFIGS.items():
        last_syncs[entity_key] = _last_sync_time(config[2])

    sync_in_progress = XeroSyncService.get_active_task_id() is not None

    return XeroSyncInfoOut(
        last_syncs=last_syncs,
        sync_range="Syncing data since last successful sync",
        sync_in_progress=sync_in_progress,
    )


# --- Xero app management (break-glass credential rotation) ---


class XeroAppOut(ResponseSchema):
    """A XeroApp row without its secrets.

    client_secret and webhook_key are write-only — never returned. The webhook
    signing key is comparable in sensitivity to the client secret (anyone
    holding it can forge webhook deliveries we would verify as authentic).
    access_token / refresh_token are not surfaced at all; the derived
    ``has_tokens`` says whether the row has been authorised.
    """

    id: UUID
    label: str
    client_id: str
    redirect_uri: str
    is_active: bool
    has_tokens: bool
    day_remaining: int | None
    minute_remaining: int | None
    snapshot_at: datetime | None
    last_429_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _app_out(app: XeroApp) -> XeroAppOut:
    return XeroAppOut(
        id=app.id,
        label=app.label,
        client_id=app.client_id,
        redirect_uri=app.redirect_uri,
        is_active=app.is_active,
        has_tokens=bool(app.access_token and app.refresh_token),
        day_remaining=app.day_remaining,
        minute_remaining=app.minute_remaining,
        snapshot_at=app.snapshot_at,
        last_429_at=app.last_429_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


class XeroAppCreateIn(Schema):
    """POST payload: both secrets are mandatory.

    A row created without either is inert (no secret → OAuth never completes;
    no webhook_key → webhooks from this app 401 forever), so the API rejects
    such payloads up front instead of letting them land and silently break
    later.
    """

    label: NonBlankText
    client_id: NonBlankText
    client_secret: NonBlankText
    redirect_uri: NonBlankText
    webhook_key: NonBlankText


class XeroAppPatchIn(Schema):
    """PATCH payload: every field optional; secrets need not be re-supplied."""

    label: NonBlankText = omittable("")
    client_id: NonBlankText = omittable("")
    client_secret: NonBlankText = omittable("")
    redirect_uri: NonBlankText = omittable("")
    webhook_key: NonBlankText = omittable("")


class XeroAppActivateOut(XeroAppOut):
    """Activation result: the app row plus the worker-restart notice."""

    restart_initiated: bool
    message: str


class XeroAppConfigOut(ResponseSchema):
    """Read-only config snapshot.

    For clients (e.g. the quota badge) that need to align UI thresholds to
    backend behaviour.
    """

    day_floor: int


class XeroAppErrorOut(ResponseSchema):
    """A refused app-management operation, with the reason."""

    detail: str


@router.get(
    "/xero/apps/",
    auth=office_auth,
    operation_id="xero_apps_list",
    response=list[XeroAppOut],
    summary="List Xero app credential pairs",
    tags=["xero"],
)
def xero_apps_list(request: HttpRequest) -> list[XeroAppOut]:
    """Every registered app row, oldest first, secrets omitted."""
    return [_app_out(app) for app in XeroApp.objects.all().order_by("created_at")]


@router.get(
    "/xero/apps/config/",
    auth=office_auth,
    operation_id="xero_apps_config",
    response=XeroAppConfigOut,
    summary="Xero integration config snapshot",
    tags=["xero"],
)
def xero_apps_config(request: HttpRequest) -> XeroAppConfigOut:
    """Expose backend Xero config to the frontend.

    Today: just the day-quota floor — the quota badge derives its red/amber
    thresholds from this so a deployment bumping the floor in CompanyDefaults
    doesn't leave the UI showing "healthy" while syncs abort.
    """
    return XeroAppConfigOut(day_floor=CompanyDefaults.get_solo().xero_automated_day_floor)


@router.post(
    "/xero/apps/",
    auth=office_auth,
    operation_id="xero_apps_create",
    response={201: XeroAppOut, 400: XeroAppErrorOut},
    summary="Register a Xero app credential pair",
    tags=["xero"],
)
def xero_apps_create(
    request: HttpRequest, payload: XeroAppCreateIn
) -> Status[XeroAppOut | XeroAppErrorOut]:
    """Create an inactive row; activation is a separate, deliberate step."""
    try:
        app = XeroApp.objects.create(
            label=payload.label,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            redirect_uri=payload.redirect_uri,
            webhook_key=payload.webhook_key,
        )
    # deliberate-swallow: creating a row with a client_id another row holds
    # is the caller's mistake, reshaped to the promised 400
    except IntegrityError:
        return Status(400, XeroAppErrorOut(detail="A XeroApp with that client_id already exists."))
    return Status(201, _app_out(app))


@router.patch(
    "/xero/apps/{uuid:app_id}/",
    auth=office_auth,
    operation_id="xero_apps_partial_update",
    response={200: XeroAppOut, 400: XeroAppErrorOut},
    summary="Update a Xero app credential pair",
    tags=["xero"],
)
def xero_apps_partial_update(
    request: HttpRequest, app_id: UUID, payload: XeroAppPatchIn
) -> Status[XeroAppOut | XeroAppErrorOut]:
    """Apply the supplied fields; a credential change invalidates tokens.

    A new client_id (or secret) is a different Xero app from Xero's
    perspective — the old tokens and quota state are wiped, and if the row is
    active the in-process ApiClient singleton resets and sibling workers
    restart, exactly as an activation swap would.
    """
    app = get_object_or_404(XeroApp, id=app_id)
    before_client_id = app.client_id
    before_client_secret = app.client_secret

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(app, field, value)
    try:
        app.save(update_fields=[*updates.keys(), "updated_at"] if updates else None)
    # deliberate-swallow: rotating a row ONTO a client_id its sibling holds
    # is the caller's mistake, reshaped to the promised 400
    except IntegrityError:
        return Status(400, XeroAppErrorOut(detail="A XeroApp with that client_id already exists."))

    credentials_changed = (
        app.client_id != before_client_id or app.client_secret != before_client_secret
    )
    if credentials_changed:
        wipe_tokens_and_quota(app)
        if app.is_active:
            # The process-level ApiClient singleton was built from the old
            # credentials; without this reset its next call would use stale
            # client_id/secret. Sibling workers hold their own singletons —
            # restart them the same way swap_active does.
            xero_auth._reset_api_client()
            try:
                _restart_sibling_workers()
            # deliberate-swallow: the credential change is already committed
            # and the tokens wiped — a 500 here would tell the operator the
            # rotation failed when it succeeded. The restart failure is
            # persisted inside _restart_sibling_workers before it raises.
            except Exception:  # noqa: BLE001
                logger.error("Sibling-worker restart failed after credential change")
        app.refresh_from_db()
    return Status(200, _app_out(app))


@router.delete(
    "/xero/apps/{uuid:app_id}/",
    auth=office_auth,
    operation_id="xero_apps_destroy",
    response={204: None, 400: XeroAppErrorOut},
    summary="Delete a Xero app credential pair",
    tags=["xero"],
)
def xero_apps_destroy(request: HttpRequest, app_id: UUID) -> Status[XeroAppErrorOut | None]:
    """Delete an inactive row; the active row is protected."""
    # Row lock: without it a concurrent activate can flip is_active between
    # the check and the delete, leaving the install with zero active rows.
    with transaction.atomic():
        app = get_object_or_404(XeroApp.objects.select_for_update(), id=app_id)
        if app.is_active:
            return Status(
                400,
                XeroAppErrorOut(
                    detail="Cannot delete the active XeroApp. Activate another row first."
                ),
            )
        app.delete()
    return Status(204, None)


@router.post(
    "/xero/apps/{uuid:app_id}/activate/",
    auth=office_auth,
    operation_id="xero_apps_activate",
    response=XeroAppActivateOut,
    summary="Make this Xero app the active credential pair",
    tags=["xero"],
)
def xero_apps_activate(request: HttpRequest, app_id: UUID) -> XeroAppActivateOut:
    """Swap the active row; workers restart to rebuild their clients.

    swap_active dispatches a detached ``systemctl restart`` for the worker
    units — gunicorn (this process) included. The HTTP response gets out
    before systemd kills us; the operator's next request lands on a fresh
    worker bound to the new active row.
    """
    get_object_or_404(XeroApp, id=app_id)
    try:
        target = swap_active(app_id)
    except Exception as exc:
        persist_app_error(exc)
        raise
    base = _app_out(target)
    return XeroAppActivateOut(
        **base.model_dump(),
        restart_initiated=True,
        message=(
            "Active Xero app swapped. Workers are restarting; "
            "this page will refresh in a few seconds."
        ),
    )
