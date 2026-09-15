"""Xero OAuth browser flow — plain Django views, deliberately outside ninja.

Exact-URL parity: Xero's developer portal and every ``XeroApp.redirect_uri``
row hold ``/api/xero/oauth/callback/`` verbatim, so these views mount in
``config/urls.py`` ahead of the ninja API and never appear in the exported
OpenAPI schema (they speak browser-redirect, not JSON).

Being outside ninja, they also sit outside ninja's auth classes — so
``xero_authenticate`` enforces the office-staff cookie-JWT itself (v1 left it
anonymous; letting any visitor start a flow that overwrites the active app's
tokens is a connection-clobbering hole, ADR 0002). The callback stays
anonymous — Xero's redirect carries no auth — and is bound to the initiating
request by the ``state``: minted only for office staff, unguessable,
single-use and short-lived, held in the shared cache with the absolute URL
the browser came from. The session was the rejected alternative: it bound
the flow to one hostname, and an instance alias starts the flow on a host
Xero never redirects to (the registered URI is the canonical host's), so the
alias's session cookie was never presented to the callback. Binding to the
browser bought nothing beyond the office-staff gate anyway: what the exchange
overwrites is the instance-wide XeroApp token row, not anything of the user's.
"""

import logging
import re
import uuid
from urllib.parse import urlencode

from django.core.cache import caches
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from xero_python.identity import IdentityApi

from apps.core.auth import OfficeStaffCookieJWTAuth
from apps.xero.auth import exchange_code_for_token, get_api_client, get_authentication_url
from apps.xero.constants import OAUTH_STATE_TTL_SECONDS, oauth_state_key

logger = logging.getLogger(__name__)
_shared_cache = caches["shared"]

# A path on this host and nothing else: ``//evil`` is scheme-relative and
# build_absolute_uri would resolve it to ``https://evil``.
_NEXT_PATH = re.compile(r"^/(?!/)")


def _require_office_staff(request: HttpRequest) -> HttpResponse | None:
    """Reject the request unless the office-staff cookie JWT authenticates."""
    auth = OfficeStaffCookieJWTAuth()
    try:
        user = auth.authenticate(request, request.COOKIES.get(auth.param_name))
    # deliberate-swallow: the auth class raises its authorization error for
    # a non-office user; every failure mode here has the same one answer, the
    # 403 below
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        logger.warning("Rejected unauthenticated request to %s", request.path)
        return HttpResponseForbidden("Office staff only")
    return None


@csrf_exempt
def xero_authenticate(request: HttpRequest) -> HttpResponse:
    """Step 1: mint the state, remember where to return, redirect to Xero's consent page."""
    guard = _require_office_staff(request)
    if guard is not None:
        return guard
    next_path = request.GET.get("next", "/")
    if not _NEXT_PATH.match(next_path):
        return HttpResponseBadRequest("next must be a path on this host")
    state = str(uuid.uuid4())
    # The request's own origin: the canonical host, an alias, or the dev
    # tunnel — whichever the browser is on is where it lands afterwards.
    _shared_cache.set(
        oauth_state_key(state), request.build_absolute_uri(next_path), OAUTH_STATE_TTL_SECONDS
    )
    return redirect(get_authentication_url(state))


def _error_redirect(return_to: str, message: str) -> HttpResponse:
    return redirect(f"{return_to}?{urlencode({'xero_error': message})}")


def _consume_state(request: HttpRequest) -> str | None:
    """Return the address a live state was minted for, spending it; None for any other state.

    The state must be one xero_authenticate minted — otherwise an
    attacker-supplied callback URL could bind the install to a foreign Xero
    account (classic OAuth login-CSRF). v1 stored the state and never compared
    it; the check is the point. Consumed before anything else so every landing,
    error or not, goes back to the host the flow started on.
    """
    state = request.GET.get("state")
    if not state:
        logger.warning("Xero OAuth callback arrived without a state; rejecting code exchange")
        return None
    key = oauth_state_key(state)
    return_to: str | None = _shared_cache.get(key)
    # delete() reports whether the key was still there: two callbacks racing
    # on one state cannot both pass, where a plain get-then-delete would let them.
    if return_to is None or not _shared_cache.delete(key):
        logger.warning("Xero OAuth callback state mismatch; rejecting code exchange")
        return None
    return return_to


@csrf_exempt
def xero_oauth_callback(request: HttpRequest) -> HttpResponse:
    """Step 2: exchange the authorization code and bounce back to where the flow started.

    Errors (user denied consent, missing code, state mismatch, Xero-reported
    failure) land on the frontend with an ``xero_error`` query parameter
    rather than a server error page — the SPA owns presentation.
    """
    return_to = _consume_state(request)
    if return_to is None:
        return _error_redirect(
            request.build_absolute_uri("/"), "OAuth state mismatch — please retry the connection"
        )

    error = request.GET.get("error")
    if error:
        error_description = request.GET.get("error_description", error)
        logger.info("Xero OAuth cancelled or denied: %s", error_description)
        return _error_redirect(return_to, error_description)

    code = request.GET.get("code")
    if not code:
        logger.warning("Xero OAuth callback arrived without a code parameter")
        return _error_redirect(return_to, "Xero returned no authorization code")

    try:
        result = exchange_code_for_token(code)
    # deliberate-swallow: exchange_code_for_token already persisted the
    # AppError; a browser flow must land on the SPA with xero_error, not a
    # 500 page
    except Exception as exc:  # noqa: BLE001
        logger.warning("Xero code exchange failed: %s", exc)
        return _error_redirect(return_to, "Xero rejected the authorization code")
    if "error" in result:
        return _error_redirect(return_to, str(result["error"]))

    try:
        identity_api = IdentityApi(get_api_client())
        connections = identity_api.get_connections()
        if connections:
            logger.info("Available Xero Organizations after authentication:")
            for conn in connections:
                logger.info("Tenant ID: %s, Name: %s", conn.tenant_id, conn.tenant_name)
        else:
            logger.info("No Xero organizations found after authentication")
    # deliberate-swallow: diagnostic logging only; the tokens are already
    # stored and the user must still land on the SPA
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to log available tenant IDs after authentication: %s", exc)

    logger.info("Redirecting user to frontend: %s", return_to)
    return redirect(return_to)
