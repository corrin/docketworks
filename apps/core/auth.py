"""Authentication for the single NinjaAPI, ported from v1 apps/workflow/authentication.py.

- ``CookieJWTAuth`` validates the JWT access token carried in the same HttpOnly
  cookie v1 used (``SIMPLE_JWT["AUTH_COOKIE"]``, default ``access_token``) via
  django-ninja-jwt. ninja_jwt reads the ``SIMPLE_JWT`` settings dict directly and
  its token classes emit/accept the same claims (``token_type``, ``user_id``,
  ``jti``, ``exp``, ``iat``) signed HS256 with ``SECRET_KEY``, so access and
  refresh tokens minted by v1 stay valid in v2.
- ``ServiceAPIKeyAuth`` validates the ``X-API-Key`` header against
  ``apps.core.models.ServiceAPIKey`` (v1 ServiceAPIKeyAuthentication).

The cookie read/write helpers live here as the one implementation of the JWT
cookie contract; the accounts login/refresh/logout endpoints use them so the
auth class and the endpoints can never disagree on names or flags.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, cast

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpRequest, HttpResponse
from ninja.security import APIKeyCookie, APIKeyHeader
from ninja_jwt.authentication import JWTBaseAuthentication
from ninja_jwt.exceptions import AuthenticationFailed, InvalidToken, TokenError

from apps.core.models import ServiceAPIKey

logger = logging.getLogger(__name__)


SameSite = Literal["Lax", "Strict", "None"]


@dataclass(frozen=True, slots=True)
class JWTCookieConfig:
    """The JWT cookie contract: names, lifetimes and flags from settings.SIMPLE_JWT.

    Fallback defaults mirror v1's settings values so behaviour is identical
    even before/without the settings block being wired.
    """

    access_name: str
    refresh_name: str
    access_max_age: int
    refresh_max_age: int
    access_secure: bool
    access_httponly: bool
    access_samesite: SameSite
    refresh_secure: bool
    refresh_httponly: bool
    refresh_samesite: SameSite
    domain: str | None


def jwt_cookie_config() -> JWTCookieConfig:
    """Read the cookie contract from settings.SIMPLE_JWT (v1 names, v1 defaults)."""
    conf: Mapping[str, object] = getattr(settings, "SIMPLE_JWT", {})
    access_lifetime = cast("timedelta", conf.get("ACCESS_TOKEN_LIFETIME", timedelta(days=30)))
    refresh_lifetime = cast("timedelta", conf.get("REFRESH_TOKEN_LIFETIME", timedelta(days=90)))
    return JWTCookieConfig(
        access_name=cast("str", conf.get("AUTH_COOKIE", "access_token")),
        refresh_name=cast("str", conf.get("REFRESH_COOKIE", "refresh_token")),
        access_max_age=int(access_lifetime.total_seconds()),
        refresh_max_age=int(refresh_lifetime.total_seconds()),
        access_secure=cast("bool", conf.get("AUTH_COOKIE_SECURE", not settings.DEBUG)),
        access_httponly=cast("bool", conf.get("AUTH_COOKIE_HTTP_ONLY", True)),
        access_samesite=cast("SameSite", conf.get("AUTH_COOKIE_SAMESITE", "Lax")),
        refresh_secure=cast("bool", conf.get("REFRESH_COOKIE_SECURE", not settings.DEBUG)),
        refresh_httponly=cast("bool", conf.get("REFRESH_COOKIE_HTTP_ONLY", True)),
        refresh_samesite=cast("SameSite", conf.get("REFRESH_COOKIE_SAMESITE", "Lax")),
        domain=cast("str | None", conf.get("AUTH_COOKIE_DOMAIN")),
    )


def set_access_cookie(response: HttpResponse, access_token: str) -> None:
    """Set the HttpOnly access-token cookie exactly as v1's login/refresh views did."""
    conf = jwt_cookie_config()
    response.set_cookie(
        conf.access_name,
        access_token,
        max_age=conf.access_max_age,
        httponly=conf.access_httponly,
        secure=conf.access_secure,
        samesite=conf.access_samesite,
        domain=conf.domain,
    )


def set_refresh_cookie(response: HttpResponse, refresh_token: str) -> None:
    """Set the HttpOnly refresh-token cookie exactly as v1's login view did."""
    conf = jwt_cookie_config()
    response.set_cookie(
        conf.refresh_name,
        refresh_token,
        max_age=conf.refresh_max_age,
        httponly=conf.refresh_httponly,
        secure=conf.refresh_secure,
        samesite=conf.refresh_samesite,
        domain=conf.domain,
    )


def clear_auth_cookies(response: HttpResponse) -> None:
    """Delete both JWT cookies exactly as v1's LogoutUserAPIView did."""
    conf = jwt_cookie_config()
    response.delete_cookie(conf.access_name, domain=conf.domain, samesite=conf.access_samesite)
    response.delete_cookie(conf.refresh_name, domain=conf.domain, samesite=conf.refresh_samesite)


def _user_is_currently_active(user: AbstractBaseUser) -> bool:
    """v1 rejected staff whose employment ended (Staff.is_currently_active).

    Duck-typed because core must not import the accounts app (layer contract:
    domain apps import core, never the reverse).
    """
    active: bool = getattr(user, "is_currently_active", True)
    return active


class CookieJWTAuth(JWTBaseAuthentication, APIKeyCookie):
    """JWT auth from the HttpOnly access-token cookie (v1 JWTAuthentication).

    Reads ONLY the cookie (never the Authorization header), like v1. CSRF is
    not enforced: v1's DRF JWTAuthentication performed no CSRF check for
    cookie-borne JWTs (the cookies are SameSite=Lax), and the v1 frontend sends
    no CSRF token on API calls.
    """

    def __init__(self) -> None:
        """Bind the cookie name from settings and disable ninja's CSRF check."""
        self.param_name = jwt_cookie_config().access_name
        super().__init__()
        self.csrf = False  # parity with v1; see class docstring

    def authenticate(self, request: HttpRequest, key: str | None) -> AbstractBaseUser | None:
        """Validate the access-token cookie and return its active user, else None."""
        if not key:
            logger.info(
                "JWT AUTH MISS - method=%s path=%s access_cookie_present=False "
                "refresh_cookie_present=%s",
                request.method,
                request.path,
                jwt_cookie_config().refresh_name in request.COOKIES,
            )
            return None
        try:
            user = self.jwt_authenticate(request, key)
        except (InvalidToken, TokenError, AuthenticationFailed) as exc:
            logger.info(
                "JWT AUTH INVALID - method=%s path=%s refresh_cookie_present=%s error=%s",
                request.method,
                request.path,
                jwt_cookie_config().refresh_name in request.COOKIES,
                exc,
            )
            return None
        if not _user_is_currently_active(user):
            logger.info("JWT AUTH REJECTED - inactive user pk=%s path=%s", user.pk, request.path)
            return None
        if getattr(user, "password_needs_reset", False):
            logger.warning("User pk=%s authenticated via JWT but needs to reset password.", user.pk)
        return user


class ServiceAPIKeyAuth(APIKeyHeader):
    """Service-to-service auth via the X-API-Key header (v1 ServiceAPIKeyAuthentication)."""

    param_name = "X-API-Key"

    def authenticate(self, request: HttpRequest, key: str | None) -> ServiceAPIKey | None:
        """Look up an active ServiceAPIKey for the header value, else None."""
        if not key:
            return None
        try:
            service_key = ServiceAPIKey.objects.get(key=key, is_active=True)
        except ServiceAPIKey.DoesNotExist:
            logger.warning(
                "SERVICE API KEY INVALID - method=%s path=%s", request.method, request.path
            )
            return None
        service_key.mark_used()
        return service_key
