import logging
from datetime import datetime
from typing import Callable

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import DisallowedHost
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from apps.workflow.services.error_persistence import persist_and_raise
from jobs_manager.authentication import JWTAuthentication

# Get access logger configured in Django settings
access_logger = logging.getLogger("access")


class DisallowedHostMiddleware:
    """
    Middleware to catch DisallowedHost exceptions and return a clean 400 response.

    This prevents break-in attempts from filling logs with tracebacks while still
    rejecting the requests appropriately.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        """Handle DisallowedHost exceptions without traceback."""
        if isinstance(exception, DisallowedHost):
            # Extract IP from the exception message
            msg = str(exception)
            if "'" in msg:
                ip = msg.split("'")[1]
                access_logger.warning(f"Request from unknown IP {ip}")
            else:
                access_logger.warning(f"Request from unknown host: {msg}")

            # Return 400 Bad Request without traceback
            return HttpResponse("Bad Request", status=400)

        # Let other exceptions propagate normally
        return None


class AccessLoggingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Try to authenticate with JWT if not already authenticated
        if not request.user.is_authenticated:
            jwt_auth = JWTAuthentication()
            try:
                auth_result = jwt_auth.authenticate(request)
                if auth_result:
                    request.user, _ = auth_result
            except Exception:
                # If JWT authentication fails, continue with anonymous user
                pass

        # Handle unhappy case first - unauthenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Log authenticated user access
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            user = getattr(request.user, "email", str(request.user))
            page = request.path
            method = request.method

            access_logger.info(f"{timestamp}\t{method}\t{user}\t{page}")
        except Exception as e:
            # Log any errors that occur during logging
            access_logger.error(f"Error logging access: {e}")
            persist_and_raise(e)
        return self.get_response(request)


class FrontendRedirectMiddleware:
    """
    Middleware that forces browser requests to redirect to the frontend.
    The backend should serve ONLY APIs - any browser request goes to the frontend.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Skip for static files
        if self._is_static_request(request):
            return self.get_response(request)

        # Django admin should also be redirected to frontend
        # If you want to keep admin accessible, uncomment the line below:
        # if request.path_info.startswith("/admin/"):
        #     return self.get_response(request)

        # Skip for specific endpoints that should work
        if self._is_allowed_backend_endpoint(request):
            return self.get_response(request)

        # If it's a browser request (not API), redirect to frontend
        if self._is_browser_request(request):
            return self._redirect_to_frontend(request)

        return self.get_response(request)

    def _is_static_request(self, request: HttpRequest) -> bool:
        """Check if it's a request for static files."""
        static_paths = ["/static/", "/media/", "/favicon.ico", "/__debug__/"]
        return any(request.path_info.startswith(path) for path in static_paths)

    def _is_allowed_backend_endpoint(self, request: HttpRequest) -> bool:
        """
        Endpoints that should continue working on the backend.
        Uses API_PATH_PREFIXES from settings as single source of truth.
        """
        # Use API_PATH_PREFIXES from settings (single source of truth)
        allowed_patterns = getattr(settings, "API_PATH_PREFIXES", [])

        # Specific endpoints that need to work
        specific_endpoints = [
            "/api/xero/oauth/callback/",  # Xero OAuth callback
            "/api/xero/webhook/",  # Xero webhook
        ]

        # Check patterns
        for pattern in allowed_patterns:
            if request.path_info.startswith(pattern):
                return True

        # Check specific endpoints
        if request.path_info in specific_endpoints:
            return True

        return False

    def _is_browser_request(self, request: HttpRequest) -> bool:
        """
        Detect if it's a browser request vs API client.
        """
        user_agent = request.headers.get("User-Agent", "").lower()
        accept_header = request.headers.get("Accept", "").lower()

        # If it accepts HTML, it's probably a browser
        if "text/html" in accept_header:
            return True

        # If it has a known browser User-Agent
        browser_indicators = ["mozilla", "chrome", "safari", "firefox", "edge", "opera"]
        if any(indicator in user_agent for indicator in browser_indicators):
            # But if it explicitly requests JSON, treat as API
            if "application/json" in accept_header:
                return False
            return True

        return False

    def _redirect_to_frontend(self, request: HttpRequest) -> HttpResponse:
        """
        Redirect browser requests to the frontend.
        """
        frontend_url = getattr(settings, "FRONT_END_URL", "")

        if not frontend_url:
            # If FRONT_END_URL is not configured, return error
            return JsonResponse(
                {
                    "error": "Backend is API-only. Frontend URL not configured.",
                    "message": "This backend serves only APIs. Please configure FRONT_END_URL in settings.",
                },
                status=503,
            )

        # Redirect to frontend root
        frontend_root = frontend_url.rstrip("/") + "/"

        # Log the redirection
        access_logger.info(
            f"Redirecting browser request from {request.path} to {frontend_root}"
        )

        return redirect(frontend_root)


class LoginRequiredMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.exempt_urls = []
        self.exempt_url_prefixes = []

        if hasattr(settings, "LOGIN_EXEMPT_URLS"):
            for url_name in settings.LOGIN_EXEMPT_URLS:
                # Add support for Xero endpoints with dynamic UUIDs
                if (
                    url_name.startswith("api/xero/create_invoice/")
                    or url_name.startswith("api/xero/create_quote/")
                    or url_name.startswith("api/xero/delete_invoice/")
                    or url_name.startswith("api/xero/delete_quote/")
                ):
                    self.exempt_url_prefixes.append(url_name)
                    continue
                try:
                    # Try to resolve the URL name to an actual path
                    self.exempt_urls.append(reverse(url_name))
                except Exception:
                    # If it fails, we assume it's a prefix and add it directly
                    self.exempt_url_prefixes.append(url_name)

        # Add /api/schema/ to allowany whitelist for unauthenticated access
        self.exempt_url_prefixes.append("/api/schema/")

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Debug logging for client create endpoint
        if request.path_info == "/clients/create/":
            access_logger.info(
                f"DEBUG LoginRequiredMiddleware: Processing {request.path_info}"
            )
            access_logger.info(
                f"DEBUG LoginRequiredMiddleware: User authenticated: {request.user.is_authenticated}"
            )
            access_logger.info(
                f"DEBUG LoginRequiredMiddleware: User: {getattr(request.user, 'email', 'Anonymous')}"
            )

        # In DEBUG mode, skip login requirements entirely
        if settings.DEBUG:
            if request.path_info == "/clients/create/":
                access_logger.info(
                    "DEBUG LoginRequiredMiddleware: Skipping due to DEBUG mode"
                )
            return self.get_response(request)

        login_path = reverse("accounts:login")
        # Allow POST requests to login endpoint
        login_path = reverse("accounts:login").rstrip("/")
        req_path = request.path_info.rstrip("/")
        if request.method == "POST" and req_path == login_path:
            return self.get_response(request)
        # Check exact path matches first
        if request.path_info in self.exempt_urls:
            return self.get_response(request)  # Check path prefixes
        path = request.path_info.lstrip("/")
        if any(path.startswith(prefix) for prefix in self.exempt_url_prefixes):
            return self.get_response(request)

        # Handle logout endpoints specifically
        if request.path_info.endswith("/logout/"):
            return self.get_response(request)

        if not request.user.is_authenticated:
            # Skip authentication check for DRF endpoints - let DRF handle authentication
            # Uses API_PATH_PREFIXES from settings (single source of truth)
            drf_endpoints = getattr(settings, "API_PATH_PREFIXES", [])

            # Check if this is a DRF endpoint
            if any(
                request.path_info.startswith(endpoint) for endpoint in drf_endpoints
            ):
                if request.path_info == "/clients/create/":
                    access_logger.info(
                        f"DEBUG LoginRequiredMiddleware: Allowing DRF endpoint {request.path_info}"
                    )
                # Allow cost set endpoint without authentication for testing
                if (
                    settings.DEBUG_PAYLOAD
                    and request.path_info.startswith("/job/rest/jobs/")
                    and "cost-sets" in request.path_info
                ):
                    access_logger.info(
                        f"DEBUG LoginRequiredMiddleware: Allowing cost-set endpoint without auth {request.path_info}"
                    )
                    return self.get_response(request)
                return self.get_response(request)  # Let DRF handle authentication

            if request.path_info.startswith("/api/"):
                return JsonResponse(
                    {"detail": "Authentication credentials were not provided."},
                    status=401,
                )
            accepts_json = (
                request.headers.get("Accept", "").lower().startswith("application/json")
            )
            is_json = (
                request.headers.get("Content-Type", "")
                .lower()
                .startswith("application/json")
            )
            if accepts_json or is_json:
                return JsonResponse(
                    {"detail": "Authentication credentials were not provided."},
                    status=401,
                )
            # Always redirect to the front-end SPA login
            frontend_login_url = getattr(settings, "FRONT_END_URL", None)
            if frontend_login_url:
                return redirect(frontend_login_url.rstrip("/") + "/login")
            # If FRONT_END_URL is not set, return 401 to avoid redirect loop
            return JsonResponse(
                {"detail": "Authentication required. FRONT_END_URL not set."},
                status=401,
            )
        return self.get_response(request)


class PasswordStrengthMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if getattr(settings, "ENABLE_JWT_AUTH", False) and not hasattr(
            request, "session"
        ):
            return self.get_response(request)

        if request.user.is_authenticated and request.user.password_needs_reset:
            exempt_urls = [
                reverse("accounts:password_change"),
                reverse("accounts:password_change_done"),
                reverse("accounts:logout"),
                reverse("accounts:token_obtain_pair"),
                reverse("accounts:token_refresh"),
                reverse("accounts:token_verify"),
            ]

            if request.path not in exempt_urls and not request.path.startswith(
                "/static/"
            ):
                messages.warning(
                    request,
                    "For security reasons, you need to update your password to "
                    "meet our new requirements.",
                )
                return redirect("accounts:password_change")

        return self.get_response(request)
