import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.urls import reverse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.serializers import (
    CustomTokenObtainPairSerializer,
    EmptySerializer,
    TokenObtainPairResponseSerializer,
    TokenRefreshResponseSerializer,
)

logger = logging.getLogger(__name__)


def get_client_ip(request: HttpRequest) -> str:
    """
    Extract client IP address from request.

    Production path (behind nginx reverse proxy):
        - nginx receives client connection, knows real client IP
        - nginx sets X-Forwarded-For header with client's real IP
        - We read X-Forwarded-For

    Development path (direct connection to Django):
        - No nginx, browser connects directly to Django dev server
        - Django receives connection, REMOTE_ADDR contains real client IP
        - X-Forwarded-For not set, so we fall back to REMOTE_ADDR

    These are fundamentally different network topologies requiring different
    code paths. Both paths are tested: production via nginx config,
    development via direct connection.

    Args:
        request: Django HTTP request

    Returns:
        str: Client IP address
    """
    # Production: nginx sets X-Forwarded-For
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    remote_addr = request.META.get("REMOTE_ADDR")

    logger.debug(
        f"IP headers - X-Forwarded-For: {x_forwarded_for}, REMOTE_ADDR: {remote_addr}"
    )

    if x_forwarded_for:
        # First IP in comma-separated list is the original client
        client_ip = x_forwarded_for.split(",")[0].strip()
        logger.debug(f"Using X-Forwarded-For: {client_ip}")
        return client_ip
    elif remote_addr:
        logger.debug(f"Using REMOTE_ADDR: {remote_addr}")
        return remote_addr
    else:
        raise ValueError("Unable to determine client IP address")


@extend_schema(
    responses={
        200: TokenObtainPairResponseSerializer,
        401: EmptySerializer,
    },
    description=(
        "Obtains JWT tokens for authentication. "
        "When ENABLE_JWT_AUTH=True, tokens are set as httpOnly cookies "
        "and the response body will be an empty object. "
        "Otherwise, the response body will contain the tokens. "
        "Also checks if the user needs to reset their password."
    ),
)
class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Customized token obtain view that handles password reset requirement
    and sets JWT tokens as httpOnly cookies
    """

    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        username = request.data.get("username")
        client_ip = get_client_ip(request)

        try:
            response = super().post(request, *args, **kwargs)
        except Exception as e:
            # Log failed login attempts that raise exceptions (validation errors, etc.)
            logger.warning(
                "JWT LOGIN FAILURE - username=%s ip=%s error=%s",
                username,
                client_ip,
                str(e),
            )
            raise

        if response.status_code == status.HTTP_200_OK:
            logger.info(
                "JWT LOGIN SUCCESS - username=%s ip=%s",
                username,
                client_ip,
            )

            User = get_user_model()

            try:
                if username:
                    user = User.objects.get(email=username)

                    if (
                        hasattr(user, "password_needs_reset")
                        and user.password_needs_reset
                    ):
                        logger.info("User %s needs password reset", username)
                        response.data["password_needs_reset"] = True
                        response.data["password_reset_url"] = (
                            request.build_absolute_uri(
                                reverse("accounts:password_change")
                            )
                        )

                    if getattr(settings, "ENABLE_JWT_AUTH", False):
                        self._set_jwt_cookies(response, response.data)

            except User.DoesNotExist:
                logger.error(
                    "LOGIN SUCCESS but user lookup failed - username=%s", username
                )

        else:
            logger.warning(
                "JWT LOGIN FAILURE - username=%s ip=%s status=%s",
                username,
                client_ip,
                response.status_code,
            )

        return response

    def _set_jwt_cookies(self, response: Response, data: dict) -> None:
        """Set JWT tokens as httpOnly cookies"""
        simple_jwt_settings = getattr(settings, "SIMPLE_JWT", {})

        samesite = simple_jwt_settings.get("AUTH_COOKIE_SAMESITE", "Lax")
        secure = simple_jwt_settings.get("AUTH_COOKIE_SECURE", True)
        http_only = simple_jwt_settings.get("AUTH_COOKIE_HTTP_ONLY", True)

        # Set access token cookie
        if "access" in data:
            logger.info(
                f"Setting access token cookie with samesite: {samesite}, "
                f"secure: {secure}, httponly: {http_only}"
            )
            response.set_cookie(
                simple_jwt_settings.get("AUTH_COOKIE", "access_token"),
                data["access"],
                max_age=simple_jwt_settings.get(
                    "ACCESS_TOKEN_LIFETIME"
                ).total_seconds(),
                httponly=http_only,
                secure=secure,
                samesite=samesite,
            )
            del data["access"]

        # Set refresh token cookie
        if "refresh" in data:
            logger.debug("Setting refresh token cookie")
            response.set_cookie(
                simple_jwt_settings.get("REFRESH_COOKIE", "refresh_token"),
                data["refresh"],
                max_age=simple_jwt_settings.get(
                    "REFRESH_TOKEN_LIFETIME"
                ).total_seconds(),
                httponly=simple_jwt_settings.get("REFRESH_COOKIE_HTTP_ONLY", True),
                secure=simple_jwt_settings.get("REFRESH_COOKIE_SECURE", True),
                samesite=simple_jwt_settings.get("REFRESH_COOKIE_SAMESITE", "Lax"),
            )
            del data["refresh"]


@extend_schema(
    responses={
        200: TokenRefreshResponseSerializer,
        401: EmptySerializer,
    },
    description=(
        "Refreshes the JWT access token using a refresh token. "
        "When ENABLE_JWT_AUTH=True, the new access token is set as an "
        "httpOnly cookie and removed from the JSON response. "
        "Otherwise, the response contains the new access token."
    ),
)
class CustomTokenRefreshView(TokenRefreshView):
    """
    Customized token refresh view that uses httpOnly cookies
    """

    def post(self, request, *args, **kwargs):
        # Get refresh token from cookie if not in request data
        simple_jwt_settings = getattr(settings, "SIMPLE_JWT", {})
        refresh_cookie_name = simple_jwt_settings.get("REFRESH_COOKIE", "refresh_token")

        if "refresh" not in request.data and refresh_cookie_name in request.COOKIES:
            # Create mutable copy of request data
            request_data = request.data.copy()
            request_data["refresh"] = request.COOKIES[refresh_cookie_name]
            request._full_data = request_data

        response = super().post(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            # Set new access token as httpOnly cookie
            if getattr(settings, "ENABLE_JWT_AUTH", False):
                self._set_access_cookie(response, response.data)

        return response

    def _set_access_cookie(self, response: Response, data: dict) -> None:
        """Set access token as httpOnly cookie"""
        simple_jwt_settings = getattr(settings, "SIMPLE_JWT", {})

        if "access" in data:
            response.set_cookie(
                simple_jwt_settings.get("AUTH_COOKIE", "access_token"),
                data["access"],
                max_age=simple_jwt_settings.get(
                    "ACCESS_TOKEN_LIFETIME"
                ).total_seconds(),
                httponly=simple_jwt_settings.get("AUTH_COOKIE_HTTP_ONLY", True),
                secure=simple_jwt_settings.get("AUTH_COOKIE_SECURE", True),
                samesite=simple_jwt_settings.get("AUTH_COOKIE_SAMESITE", "Lax"),
                domain=simple_jwt_settings.get("AUTH_COOKIE_DOMAIN"),
            )
            # Remove access token from response data for security
            del data["access"]
