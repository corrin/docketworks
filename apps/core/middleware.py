"""Request middleware for access logging, authentication and resource versioning.

- ``AccessLoggingMiddleware`` — one line per authenticated request on the
  ``access`` logger, carrying the session-replay id that joins a request to its
  recording.
- ``LoginRequiredMiddleware`` — the ADR 0002 global auth gate with an explicit
  anonymous allowlist (module-level data below).
- ``ResourceVersionMiddleware`` — preserves strong OCC ETags (ADR 0003) when
  gzip weakens representation ETags.
"""

import logging
from collections.abc import Callable
from time import perf_counter
from typing import ClassVar, Final
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect

# Its own logger, not "apps.*": the per-request stream is high volume and an
# operator filters or silences it (journalctl -t / a LOGGING level change)
# without touching the business logging every service writes.
access_logger = logging.getLogger("access")

# --- ADR 0002: the anonymous surface, in one place ---------------------------
#
# Literal path data answers "what URLs accept anonymous traffic?" in one place;
# resolving names from distributed settings would obscure the public surface.

AUTH_ANON_ALLOWLIST_EXACT: Final[frozenset[str]] = frozenset(
    {
        "/api/build-id/",
        # Xero webhook deliveries carry no cookie; the HMAC signature check
        # in apps/xero/webhooks.py IS this endpoint's authentication. A
        # deliberate anonymous surface (exact-parity URL held by Xero).
        "/api/xero/webhook/",
    }
)

AUTH_ANON_ALLOWLIST_PREFIXES: Final[tuple[str, ...]] = (
    # Keep schema documents public so deployment and client tooling can inspect
    # the API without first implementing cookie authentication.
    "/api/schema/",
    "/api/openapi.json",
    "/api/docs",
    # v1 LOGIN_EXEMPT_URLS: accounts:token_obtain_pair / token_refresh /
    # token_verify / api_logout (ninja-jwt endpoints under the accounts router).
    "/api/accounts/token/",
    "/api/accounts/logout/",
    # Forgot-password (2026-08-31): the emailed uid+token pair is the
    # credential, so both the request and confirm endpoints are anonymous.
    "/api/accounts/password-reset/",
)


# v1 API_PATH_PREFIXES: requests under these prefixes pass through the gate so
# the API framework's own auth (ninja auth classes in v2, DRF in v1) is the
# authoritative check and can produce a proper 401 envelope.
API_PATH_PREFIXES: Final[tuple[str, ...]] = ("/api/",)


class AccessLoggingMiddleware:
    """Log one line per authenticated request on the ``access`` logger.

    The principal is read AFTER ``get_response``. v1 checked
    ``request.user.is_authenticated`` first and returned early when anonymous,
    which in v2 would log nothing at all: ninja auth classes set
    ``request.user`` during operation dispatch, after every middleware has run,
    so every ``/api/**`` request still looks anonymous on the way in.

    v1 also re-ran JWT authentication here to recover an email for token-auth
    calls. v2 is cookie-authenticated and ninja resolves the principal, so
    there is nothing left to recover.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the next callable, per the Django middleware protocol."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Time the request, then log it once the principal is known."""
        started_at = perf_counter()
        response = self.get_response(request)
        duration_ms = (perf_counter() - started_at) * 1000

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return response

        # No try/except around the format call: every value below is an
        # already-read scalar, so a handler here could only convert a
        # programming error into a 500 on an otherwise good response.
        access_logger.info(
            "method=%s\tstatus=%s\tduration_ms=%.2f\treplay=%s\tuser=%s\tpath=%s",
            request.method,
            response.status_code,
            duration_ms,
            _replay_id_for_log(request.headers.get("X-Session-Replay-Id")),
            user.get_username(),
            request.path,
        )
        return response


def _replay_id_for_log(header: str | None) -> str:
    r"""Return the replay id only if it is one, so the log line stays parseable.

    Opus: the access line is tab-delimited and this value is client-supplied.
    HTAB is
    legal inside an HTTP field value, so an authenticated caller sending
    `X-Session-Replay-Id: x\tuser=someone.else@example.com` would append fields
    an operator greps for as though the server had written them. A UUID cannot
    carry a delimiter, so requiring one is the whole defence.
    """
    if header is None:
        return "-"
    try:
        return str(UUID(header))
    # Opus: deliberate-swallow: a malformed header is a client's business, not an
    # error of ours; the log records that it was not usable and moves on.
    except ValueError:
        return "-"


class LoginRequiredMiddleware:
    """Global auth gate (ADR 0002): reject anonymous requests off the allowlist.

    Defense-in-depth in v2: ninja auth classes (which set ``request.user``
    during operation dispatch, after middleware) are the authoritative gate for
    ``/api/**`` — those requests pass through so ninja can 401 them with the
    standard envelope. This middleware still blocks anonymous traffic to every
    non-API path not explicitly allowlisted, exactly as v1 did.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the next callable, per the Django middleware protocol."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Pass allowlisted/authenticated/API traffic through; reject the rest."""
        # In DEBUG mode, skip login requirements entirely (v1 behaviour).
        if settings.DEBUG:
            return self.get_response(request)

        path = request.path_info
        if (
            path in AUTH_ANON_ALLOWLIST_EXACT
            or path.startswith(AUTH_ANON_ALLOWLIST_PREFIXES)
            or request.user.is_authenticated
        ):
            return self.get_response(request)

        if path.startswith(API_PATH_PREFIXES):
            # Let the ninja auth classes handle authentication (v1: "let DRF
            # handle authentication").
            return self.get_response(request)

        accepts_json = request.headers.get("Accept", "").lower().startswith("application/json")
        is_json = request.headers.get("Content-Type", "").lower().startswith("application/json")
        if accepts_json or is_json:
            return JsonResponse(
                {"detail": "Authentication credentials were not provided."},
                status=401,
            )

        # Always redirect browser requests to the front-end SPA login.
        frontend_url: str | None = getattr(settings, "FRONT_END_URL", None)
        if frontend_url:
            return redirect(frontend_url.rstrip("/") + "/login")
        # If FRONT_END_URL is not set, return 401 to avoid a redirect loop.
        return JsonResponse(
            {"detail": "Authentication required. FRONT_END_URL not set."},
            status=401,
        )


class ResourceVersionMiddleware:
    """Preserve strong OCC tokens when gzip weakens representation ETags."""

    _RESOURCE_ETAG_PREFIXES: ClassVar[tuple[str, ...]] = ('"job:', '"po:')

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the next callable, per the Django middleware protocol."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Mirror resource ETags into X-Resource-Version on the response."""
        response = self.get_response(request)
        etag = response.headers.get("ETag")
        if etag is None or not etag.startswith(self._RESOURCE_ETAG_PREFIXES):
            return response

        response.headers["X-Resource-Version"] = etag
        return response
