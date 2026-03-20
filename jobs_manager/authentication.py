import logging

from django.conf import settings
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

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
            # Debug logging for client create endpoint
            if request.path_info == "/clients/create/":
                logger.info(f"DEBUG: Authenticating request to {request.path_info}")
                logger.info(f"DEBUG: Request method: {request.method}")
                logger.info(
                    f"DEBUG: User-Agent: {request.headers.get('User-Agent', 'None')}"
                )
                logger.info(f"DEBUG: Accept: {request.headers.get('Accept', 'None')}")
                logger.info(
                    f"DEBUG: Content-Type: {request.headers.get('Content-Type', 'None')}"
                )

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
                if request.path_info == "/clients/create/":
                    logger.info(
                        f"DEBUG: JWT authentication failed for {request.path_info}"
                    )
                    logger.info(f"DEBUG: Cookie '{cookie_name}' present: {has_cookie}")
                    if has_cookie:
                        logger.info(
                            f"DEBUG: Cookie value length: {len(request.COOKIES[cookie_name])}"
                        )
                logger.info(
                    f"JWT authentication failed: no valid token found (cookie '{cookie_name}' present: {has_cookie})"
                )
                return None
            user, token = result
            if not user.is_currently_active:
                raise exceptions.AuthenticationFailed(
                    "User is inactive.", code="user_inactive"
                )
            if hasattr(user, "password_needs_reset") and user.password_needs_reset:
                logger.warning(
                    f"User {getattr(user, 'email', user)} authenticated via JWT but needs to reset password."
                )
            if request.path_info == "/clients/create/":
                logger.info(
                    f"DEBUG: JWT authentication SUCCESS for {request.path_info} - User: {user.email}"
                )
            return result
        except (InvalidToken, TokenError) as e:
            if request.path_info == "/clients/create/":
                logger.info(
                    f"DEBUG: JWT authentication EXCEPTION for {request.path_info}: {str(e)}"
                )
            logger.info(f"JWT authentication failed: {str(e)}")
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
