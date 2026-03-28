import logging

from django.conf import settings
from django.http import JsonResponse
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .models import ServiceAPIKey

logger = logging.getLogger(__name__)


class JWTAuthentication(BaseJWTAuthentication):
    """
    Custom JWT Authentication that supports both Authorization header and httpOnly cookies.
    """

    def authenticate(self, request):
        if not getattr(settings, "ENABLE_JWT_AUTH", False):
            return None

        # If user already authenticated by middleware, use that
        # Use underlying Django request to avoid triggering DRF's _authenticate() recursion
        django_request = getattr(request, "_request", request)
        if hasattr(django_request, "user") and django_request.user.is_authenticated:
            return (django_request.user, None)

        # Support DRF's force_authenticate for tests
        if (
            hasattr(request, "_force_auth_user")
            and request._force_auth_user is not None
        ):
            return (request._force_auth_user, None)

        try:
            # Only look at cookies, not Authorization header
            raw_token = self.get_raw_token_from_cookie(request)
            result = None
            if raw_token is not None:
                validated_token = self.get_validated_token(raw_token)
                user = self.get_user(validated_token)
                result = (user, validated_token)
            if result is None:
                cookie_name = getattr(settings, "SIMPLE_JWT", {}).get(
                    "AUTH_COOKIE", "access_token"
                )
                has_cookie = cookie_name in request.COOKIES
                logger.info(
                    "JWT authentication failed: no valid token found (cookie '%s' present: %s)",
                    cookie_name,
                    has_cookie,
                )
                return None
            user, token = result
            if not user.is_currently_active:
                raise exceptions.AuthenticationFailed(
                    "User is inactive.", code="user_inactive"
                )
            if hasattr(user, "password_needs_reset") and user.password_needs_reset:
                logger.warning(
                    "User %s authenticated via JWT but needs to reset password.",
                    getattr(user, "email", user),
                )
            return result
        except (InvalidToken, TokenError) as e:
            logger.info("JWT authentication failed: %s", e)
            if settings.DEBUG:
                return None
            raise exceptions.AuthenticationFailed(str(e))

    def get_raw_token_from_cookie(self, request):
        """
        Extract raw token from httpOnly cookie.
        """
        simple_jwt_settings = getattr(settings, "SIMPLE_JWT", {})
        cookie_name = simple_jwt_settings.get("AUTH_COOKIE", "access_token")
        if cookie_name and cookie_name in request.COOKIES:
            return request.COOKIES[cookie_name].encode("utf-8")
        return None


class ServiceAPIKeyAuthentication(BaseAuthentication):
    """
    Authentication for service API keys (e.g., MCP endpoints).
    Looks for 'X-API-Key' header.
    """

    def authenticate(self, request):
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            return None  # No API key provided, skip this authentication

        try:
            service_key = ServiceAPIKey.objects.get(key=api_key, is_active=True)
            service_key.mark_used()

            # Return a tuple of (user, auth) - we don't have a user for service keys
            # so we return the service key object as the "user" for authorization checks
            return (service_key, None)

        except ServiceAPIKey.DoesNotExist:
            raise AuthenticationFailed("Invalid API key")

    def authenticate_header(self, request):
        """
        Return a string to be used as the value of the `WWW-Authenticate`
        header in a `401 Unauthenticated` response.
        """
        return "X-API-Key"


def service_api_key_required(view_func):
    """
    Decorator to require service API key authentication for a view.
    Simple alternative to DRF authentication classes.
    """

    def _wrapped_view(request, *args, **kwargs):
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            return JsonResponse({"error": "API key required"}, status=401)

        try:
            service_key = ServiceAPIKey.objects.get(key=api_key, is_active=True)
            service_key.mark_used()

            # Add the service key to the request for use in the view
            request.service_key = service_key

        except ServiceAPIKey.DoesNotExist:
            return JsonResponse({"error": "Invalid API key"}, status=401)

        return view_func(request, *args, **kwargs)

    return _wrapped_view
