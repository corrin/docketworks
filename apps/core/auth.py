"""Authentication for the single Ninja API.

- ``CookieJWTAuth`` validates the JWT access token from the configured HttpOnly
  cookie via django-ninja-jwt. Token classes read ``SIMPLE_JWT`` directly and
  use its configured claims and signing key.
- ``ServiceAPIKeyAuth`` validates the ``X-API-Key`` header against
  ``apps.core.models.ServiceAPIKey``.

The cookie read/write helpers live here as the one implementation of the JWT
cookie contract; the accounts login/refresh/logout endpoints use them so the
auth class and the endpoints can never disagree on names or flags.
"""

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal, Protocol, cast, runtime_checkable

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpRequest, HttpResponse
from ninja.errors import AuthenticationError as NinjaAuthenticationError
from ninja.errors import AuthorizationError as NinjaAuthorizationError
from ninja.security import APIKeyCookie, APIKeyHeader
from ninja_jwt.authentication import JWTBaseAuthentication
from ninja_jwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from ninja_jwt.tokens import RefreshToken, Token

from apps.core.models import ServiceAPIKey

logger = logging.getLogger(__name__)


SameSite = Literal["Lax", "Strict", "None"]


class PasswordChangeRequiredError(Exception):
    """Authenticated, but the account's password must be changed first.

    Its own type, not NinjaAuthorizationError: the envelope must emit a stable
    machine code with error_id null and persist no AppError (an expected
    security outcome, ADR 0013/0038), where AuthorizationError persists.
    """


# ADR 0002's shape, one layer up: while password_needs_reset is set these are
# the ONLY reachable authenticated paths, so "what can a flagged session do?"
# is answered by reading this list. Literal paths, same reasoning as
# AUTH_ANON_ALLOWLIST. /me/ stays reachable so the SPA can resolve the session
# and read the flag; /me/password/ is the exit.
PASSWORD_CHANGE_ALLOWED_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/api/accounts/me/",
        "/api/accounts/me/password/",
    }
)


PASSWORD_FINGERPRINT_CLAIM: Final = "pwd_fp"  # noqa: S105 - a JWT claim NAME, not a secret


def password_fingerprint(user: AbstractBaseUser) -> str:
    """Fingerprint the stored password hash for binding into issued tokens.

    Fable: a digest of the salted hash, not the hash itself — a JWT payload
    is base64-readable by anyone holding the cookie value, and the stored
    hash is crack material. Sixteen hex chars is collision room to spare for
    an equality check against one user's own history.
    """
    return hashlib.sha256(user.password.encode()).hexdigest()[:16]


def issue_refresh_token(user: AbstractBaseUser) -> RefreshToken:
    """Mint the session's refresh token: for_user plus the password fingerprint.

    The one mint. The fingerprint makes a password change invalidate every
    other session's tokens (checked in CookieJWTAuth.get_user and the refresh
    endpoint) — chosen over installing token_blacklist because a blacklist
    row per logout is state to manage, while the fingerprint is derived from
    what the change already writes.
    """
    refresh = RefreshToken.for_user(user)
    refresh[PASSWORD_FINGERPRINT_CLAIM] = password_fingerprint(user)
    return refresh


@dataclass(frozen=True, slots=True)
class JWTCookieConfig:
    """The JWT cookie contract: names, lifetimes and flags from settings.SIMPLE_JWT.

    Fallback defaults keep authentication usable before a settings block is
    wired.
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
    """Read the cookie contract from settings.SIMPLE_JWT."""
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
    """Set the contracted HttpOnly access-token cookie."""
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
    """Set the contracted HttpOnly refresh-token cookie."""
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
    """Delete both JWT cookies."""
    conf = jwt_cookie_config()
    response.delete_cookie(conf.access_name, domain=conf.domain, samesite=conf.access_samesite)
    response.delete_cookie(conf.refresh_name, domain=conf.domain, samesite=conf.refresh_samesite)


def _user_is_currently_active(user: AbstractBaseUser) -> bool:
    """Reject staff whose employment has ended.

    Duck-typed because core must not import the accounts app (layer contract:
    domain apps import core, never the reverse).
    """
    active: bool = getattr(user, "is_currently_active", True)
    return active


class CookieJWTAuth(JWTBaseAuthentication, APIKeyCookie):
    """JWT auth from the HttpOnly access-token cookie.

    This contract reads only the cookie, never the Authorization header. CSRF
    is not enforced for the SameSite=Lax cookie and the SPA sends no CSRF token
    on API calls.
    """

    def __init__(self) -> None:
        """Bind the cookie name from settings and disable ninja's CSRF check."""
        self.param_name = jwt_cookie_config().access_name
        super().__init__()
        self.csrf = False  # SameSite cookie contract; see class docstring.

    def get_user(self, validated_token: Token) -> AbstractBaseUser:
        """Resolve the token's user, then require its password fingerprint current.

        A token minted before the last password change authenticates a
        credential we no longer trust — the change/reset endpoints exist to
        evict exactly that holder. Every valid token carries the claim
        (issue_refresh_token is the one mint), so one without it is refused
        by the same comparison, never grandfathered (ADR 0017).
        """
        user = super().get_user(validated_token)
        claimed = validated_token.get(PASSWORD_FINGERPRINT_CLAIM)
        if claimed != password_fingerprint(user):
            logger.info("JWT AUTH REJECTED - stale password fingerprint pk=%s", user.pk)
            raise AuthenticationFailed("Token predates the last password change.")
        return user

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
            # ADR 0038: state the specific rejection reason.
            raise NinjaAuthenticationError(message=str(exc)) from exc
        if not _user_is_currently_active(user):
            logger.info("JWT AUTH REJECTED - inactive user pk=%s path=%s", user.pk, request.path)
            raise NinjaAuthenticationError(message="User is inactive.")
        if getattr(user, "password_needs_reset", False) and (
            request.path not in PASSWORD_CHANGE_ALLOWED_PATHS
        ):
            # Fable: refused at the auth layer, not by a frontend redirect —
            # a redirect the API does not back leaves every endpoint serving
            # a session whose credential we have decided not to trust.
            logger.info(
                "JWT AUTH REFUSED - password change required pk=%s path=%s",
                user.pk,
                request.path,
            )
            raise PasswordChangeRequiredError
        return user


@runtime_checkable
class StaffPermissions(Protocol):
    """The permission flags the auth policies decide on.

    core must not import accounts (layer contract), and accounts cannot move
    below core either — ``Staff`` reaches into ``job.LabourSubtype`` for its
    default subtype, so it genuinely sits above the domain. Auth is more
    fundamental than the domain; the user model is not. That inversion is
    inherited and real.

    So the surface is NAMED here rather than probed for by attribute string,
    the same answer ``_WageBearingStaff`` gives in models.py. The gain over
    ``getattr(user, "is_superuser", False)`` is not tidiness: the getattr yields
    something the type checker cannot see, and silently returns False — opening
    nothing, but also gating nothing — if the attribute is ever renamed.
    isinstance against this narrows the type, so the flag is a checked bool and
    a rename is a type error.

    Data-member Protocols support isinstance but not issubclass; only the
    former is used here.
    """

    is_superuser: bool
    is_office_staff: bool


class OfficeStaffCookieJWTAuth(CookieJWTAuth):
    """Cookie-JWT auth that additionally requires ``Staff.is_office_staff``.

    The flag is reached through ``StaffPermissions`` because core must not
    import the accounts app. Keeping the shared policy here gives every domain
    one implementation (ADR 0039).
    """

    def authenticate(self, request: HttpRequest, key: str | None) -> AbstractBaseUser | None:
        """Authenticate via the cookie JWT, then require office-staff status."""
        user = super().authenticate(request, key)
        if user is None:
            return None
        if not (isinstance(user, StaffPermissions) and user.is_office_staff):
            raise NinjaAuthorizationError(
                message="You do not have permission to perform this action."
            )
        return user


class SuperuserCookieJWTAuth(CookieJWTAuth):
    """Cookie-JWT auth that additionally requires ``is_superuser``.

    Viewing or editing other staff members' pay data is deliberately narrower
    than office-staff access. This class sits beside the other shared auth
    policies so authentication has one home (ADR 0039).
    """

    def authenticate(self, request: HttpRequest, key: str | None) -> AbstractBaseUser | None:
        """Authenticate via the cookie JWT, then require superuser status."""
        user = super().authenticate(request, key)
        if user is None:
            return None
        if not (isinstance(user, StaffPermissions) and user.is_superuser):
            raise NinjaAuthorizationError(
                message="You do not have permission to perform this action."
            )
        return user


class ServiceAPIKeyAuth(APIKeyHeader):
    """Service-to-service auth via the X-API-Key header."""

    param_name = "X-API-Key"

    def authenticate(self, request: HttpRequest, key: str | None) -> ServiceAPIKey | None:
        """Look up an active ServiceAPIKey for the header value, else None."""
        if not key:
            return None
        try:
            service_key = ServiceAPIKey.objects.get(key=key, is_active=True)
        # deliberate-swallow: unknown key is an auth failure: logged, then rejected
        except ServiceAPIKey.DoesNotExist:
            logger.warning(
                "SERVICE API KEY INVALID - method=%s path=%s", request.method, request.path
            )
            return None
        service_key.mark_used()
        return service_key
