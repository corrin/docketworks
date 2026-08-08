"""Xero OAuth browser flow — plain Django views, deliberately outside ninja.

Exact-URL parity: Xero's developer portal and every ``XeroApp.redirect_uri``
row hold ``/api/xero/oauth/callback/`` verbatim, so these views mount in
``config/urls.py`` ahead of the ninja API and never appear in the exported
OpenAPI schema (they speak browser-redirect, not JSON).
"""

import logging
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from xero_python.identity import IdentityApi

from apps.xero.auth import exchange_code_for_token, get_api_client, get_authentication_url

logger = logging.getLogger(__name__)


@csrf_exempt
def xero_authenticate(request: HttpRequest) -> HttpResponse:
    """Step 1: stash CSRF state in the session and redirect to Xero's consent page."""
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


@csrf_exempt
def xero_oauth_callback(request: HttpRequest) -> HttpResponse:
    """Step 2: exchange the authorization code and bounce back to the frontend.

    Errors (user denied consent, missing code, Xero-reported failure) land on
    the frontend with an ``xero_error`` query parameter rather than a server
    error page — the SPA owns presentation.
    """
    redirect_path = request.session.pop("post_login_redirect", "/") or "/"

    error = request.GET.get("error")
    if error:
        error_description = request.GET.get("error_description", error)
        logger.info("Xero OAuth cancelled or denied: %s", error_description)
        return redirect(
            f"{_build_post_xero_url(redirect_path)}?{urlencode({'xero_error': error_description})}"
        )

    code = request.GET.get("code")
    if not code:
        logger.warning("Xero OAuth callback arrived without a code parameter")
        return redirect(
            f"{_build_post_xero_url(redirect_path)}?"
            f"{urlencode({'xero_error': 'Xero returned no authorization code'})}"
        )

    state = request.GET.get("state") or ""
    session_state = request.session.get("oauth_state") or ""
    result = exchange_code_for_token(code, state, session_state)
    if "error" in result:
        return redirect(
            f"{_build_post_xero_url(redirect_path)}?{urlencode({'xero_error': result['error']})}"
        )

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
