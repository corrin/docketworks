"""Xero OAuth browser flow — plain Django views, deliberately outside ninja.

Exact-URL parity: Xero's developer portal and every ``XeroApp.redirect_uri``
row hold ``/api/xero/oauth/callback/`` verbatim, so these views mount in
``config/urls.py`` ahead of the ninja API and never appear in the exported
OpenAPI schema (they speak browser-redirect, not JSON).

Being outside ninja, they also sit outside ninja's auth classes — so
``xero_authenticate`` enforces the office-staff cookie-JWT itself (v1 left it
anonymous; letting any visitor start a flow that overwrites the active app's
tokens is a connection-clobbering hole, ADR 0002). The callback stays
anonymous — Xero's redirect carries no auth — and is instead bound to the
initiating browser by the ``state`` check.
"""

import logging
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from xero_python.identity import IdentityApi

from apps.core.auth import OfficeStaffCookieJWTAuth
from apps.xero.auth import exchange_code_for_token, get_api_client, get_authentication_url

logger = logging.getLogger(__name__)


def _require_office_staff(request: HttpRequest) -> HttpResponse | None:
    """Reject the request unless the office-staff cookie JWT authenticates."""
    auth = OfficeStaffCookieJWTAuth()
    try:
        user = auth.authenticate(request, request.COOKIES.get(auth.param_name))
    except Exception:  # noqa: BLE001 -- the auth class raises its authorization error; any failure is a 403 here
        user = None
    if user is None:
        logger.warning("Rejected unauthenticated request to %s", request.path)
        return HttpResponseForbidden("Office staff only")
    return None


@csrf_exempt
def xero_authenticate(request: HttpRequest) -> HttpResponse:
    """Step 1: stash CSRF state in the session and redirect to Xero's consent page."""
    guard = _require_office_staff(request)
    if guard is not None:
        return guard
    state = str(uuid.uuid4())
    request.session["oauth_state"] = state
    redirect_after_login = request.GET.get("next", "/")
    request.session["post_login_redirect"] = redirect_after_login
    authorization_url = get_authentication_url(state)
    return redirect(authorization_url)


def _build_post_xero_url(redirect_path: str) -> str:
    """Absolute frontend URL to land on after the OAuth round-trip."""
    frontend_url = settings.FRONT_END_URL
    if not redirect_path.startswith("/"):
        return frontend_url.rstrip("/") + "/"
    return frontend_url.rstrip("/") + redirect_path


def _error_redirect(redirect_path: str, message: str) -> HttpResponse:
    return redirect(f"{_build_post_xero_url(redirect_path)}?{urlencode({'xero_error': message})}")


@csrf_exempt
def xero_oauth_callback(request: HttpRequest) -> HttpResponse:
    """Step 2: exchange the authorization code and bounce back to the frontend.

    Errors (user denied consent, missing code, state mismatch, Xero-reported
    failure) land on the frontend with an ``xero_error`` query parameter
    rather than a server error page — the SPA owns presentation.
    """
    redirect_path = request.session.pop("post_login_redirect", "/") or "/"

    error = request.GET.get("error")
    if error:
        error_description = request.GET.get("error_description", error)
        logger.info("Xero OAuth cancelled or denied: %s", error_description)
        return _error_redirect(redirect_path, error_description)

    code = request.GET.get("code")
    if not code:
        logger.warning("Xero OAuth callback arrived without a code parameter")
        return _error_redirect(redirect_path, "Xero returned no authorization code")

    # The state must match what THIS browser's session minted in
    # xero_authenticate — otherwise an attacker-supplied callback URL could
    # bind the install to a foreign Xero account (classic OAuth login-CSRF).
    # v1 stored the state and never compared it; the check is the point.
    state = request.GET.get("state")
    session_state = request.session.pop("oauth_state", None)
    if not state or not session_state or state != session_state:
        logger.warning("Xero OAuth callback state mismatch; rejecting code exchange")
        return _error_redirect(redirect_path, "OAuth state mismatch — please retry the connection")

    try:
        result = exchange_code_for_token(code)
    except Exception as exc:  # noqa: BLE001 -- already persisted inside; a browser flow must land on the SPA, not a 500 page
        logger.warning("Xero code exchange failed: %s", exc)
        return _error_redirect(redirect_path, "Xero rejected the authorization code")
    if "error" in result:
        return _error_redirect(redirect_path, str(result["error"]))

    try:
        identity_api = IdentityApi(get_api_client())
        connections = identity_api.get_connections()
        if connections:
            logger.info("Available Xero Organizations after authentication:")
            for conn in connections:
                logger.info("Tenant ID: %s, Name: %s", conn.tenant_id, conn.tenant_name)
        else:
            logger.info("No Xero organizations found after authentication")
    except Exception as exc:  # noqa: BLE001 -- diagnostic logging only; the tokens are already stored
        logger.warning("Failed to log available tenant IDs after authentication: %s", exc)

    redirect_url = _build_post_xero_url(redirect_path)
    logger.info("Redirecting user to frontend: %s", redirect_url)
    return redirect(redirect_url)
