"""Request middleware ported from v1 ``apps/workflow/middleware.py``.

- ``LoginRequiredMiddleware`` — the ADR 0002 global auth gate with an explicit
  anonymous allowlist (module-level data below).
- ``ResourceVersionMiddleware`` — preserves strong OCC ETags (ADR 0003) when
  gzip weakens representation ETags.
"""

from collections.abc import Callable
from typing import ClassVar, Final

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect

# --- ADR 0002: the anonymous surface, in one place ---------------------------
#
# v1 kept this list in settings (LOGIN_EXEMPT_URLS, resolved by URL name at
# middleware init). v2 keeps it as literal path data so "what URLs accept
# anonymous traffic?" is answered by reading this block.

# v1 LOGIN_EXEMPT_URLS entry "build_id" (/api/build-id/ — AllowAny in v1).
AUTH_ANON_ALLOWLIST_EXACT: Final[frozenset[str]] = frozenset(
    {
        "/api/build-id/",
    }
)

AUTH_ANON_ALLOWLIST_PREFIXES: Final[tuple[str, ...]] = (
    # v1 whitelisted /api/schema/ for unauthenticated access; ninja serves the
    # equivalent documents at /api/openapi.json and /api/docs.
    "/api/schema/",
    "/api/openapi.json",
    "/api/docs",
    # v1 LOGIN_EXEMPT_URLS: accounts:token_obtain_pair / token_refresh /
    # token_verify / api_logout (ninja-jwt endpoints under the accounts router).
    "/api/accounts/token/",
    "/api/accounts/logout/",
)


# v1 API_PATH_PREFIXES: requests under these prefixes pass through the gate so
# the API framework's own auth (ninja auth classes in v2, DRF in v1) is the
# authoritative check and can produce a proper 401 envelope.
API_PATH_PREFIXES: Final[tuple[str, ...]] = ("/api/",)


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
