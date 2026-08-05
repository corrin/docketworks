"""Authentication and user-profile endpoints.

Paths and operationIds are the stable contract in ``frontend/schema.yml``:

- POST /api/accounts/token/          accounts_token_create          (login)
- POST /api/accounts/token/refresh/  accounts_token_refresh_create
- POST /api/accounts/logout/         accounts_logout_create
- GET  /api/accounts/me/             accounts_me_retrieve

Integration wiring (config/api.py): ``api.add_router("/accounts/", router)``.
"""

import logging

from django.contrib.auth import authenticate
from django.http import HttpRequest, HttpResponse
from ninja import Router
from ninja.errors import AuthenticationError
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import Staff
from apps.accounts.schemas import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserProfile,
)
from apps.core.auth import (
    CookieJWTAuth,
    clear_auth_cookies,
    jwt_cookie_config,
    set_access_cookie,
    set_refresh_cookie,
)

logger = logging.getLogger(__name__)

router = Router(tags=["accounts"])


@router.post(
    "/token/",
    auth=None,
    operation_id="accounts_token_create",
    response=LoginResponse,
    exclude_none=True,
    summary="Obtain JWT tokens as HttpOnly cookies (login)",
)
def login(request: HttpRequest, response: HttpResponse, payload: LoginRequest) -> LoginResponse:
    """Authenticate and set the JWT cookies.

    Authenticates username(=email)/password, sets access+refresh HttpOnly
    cookies, and returns an empty body (plus password_needs_reset when the
    user must change their password).
    """
    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None or not isinstance(user, Staff):
        logger.warning("JWT LOGIN FAILURE - username=%s", payload.username)
        raise AuthenticationError
    if not user.is_currently_active:
        # Departed staff must be rejected at login, not merely on
        # follow-up requests — otherwise valid cookies + per-request 401s
        # trap them in a silent login/redirect loop.
        logger.warning("JWT LOGIN REJECTED - inactive user username=%s", payload.username)
        raise AuthenticationError(message="User is inactive.")
    refresh = RefreshToken.for_user(user)
    set_access_cookie(response, str(refresh.access_token))
    set_refresh_cookie(response, str(refresh))
    logger.info("JWT LOGIN SUCCESS - username=%s", payload.username)
    if user.password_needs_reset:
        logger.info("User %s needs password reset", payload.username)
        return LoginResponse(password_needs_reset=True)
    return LoginResponse()


@router.post(
    "/token/refresh/",
    auth=None,
    operation_id="accounts_token_refresh_create",
    response=TokenRefreshResponse,
    summary="Refresh the access-token cookie from the refresh token",
)
def token_refresh(
    request: HttpRequest,
    response: HttpResponse,
    payload: TokenRefreshRequest | None = None,
) -> TokenRefreshResponse:
    """Rotate the access-token cookie.

    Takes the refresh token from the body or the refresh cookie, rotates the
    access cookie, and returns an empty body. Refresh tokens are not rotated
    by design.
    """
    raw_refresh = payload.refresh if payload is not None else None
    if not raw_refresh:
        raw_refresh = request.COOKIES.get(jwt_cookie_config().refresh_name)
    if not raw_refresh:
        logger.info("JWT REFRESH FAILURE - no refresh token in body or cookie")
        raise AuthenticationError
    try:
        refresh = RefreshToken(raw_refresh)
    except TokenError as exc:
        logger.info("JWT REFRESH FAILURE - invalid refresh token: %s", exc)
        raise AuthenticationError from exc
    set_access_cookie(response, str(refresh.access_token))
    return TokenRefreshResponse()


@router.post(
    "/logout/",
    auth=None,
    operation_id="accounts_logout_create",
    response=LogoutResponse,
    summary="Logs out the current user by clearing JWT cookies",
)
def logout(request: HttpRequest, response: HttpResponse) -> LogoutResponse:
    """Clear both JWT cookies; logout never requires authentication."""
    conf = jwt_cookie_config()
    logger.info(
        "JWT LOGOUT REQUEST - access_cookie_present=%s refresh_cookie_present=%s",
        conf.access_name in request.COOKIES,
        conf.refresh_name in request.COOKIES,
    )
    clear_auth_cookies(response)
    return LogoutResponse(success=True, message="Successfully logged out")


@router.get(
    "/me/",
    auth=CookieJWTAuth(),
    operation_id="accounts_me_retrieve",
    response=UserProfile,
    by_alias=True,  # Emit the contracted ``fullName`` serialization alias.
    summary="Returns the current authenticated user profile",
)
def me(request: HttpRequest) -> Staff:
    """Return the authenticated user's profile.

    The SPA's session probe. CookieJWTAuth has already set request.user; no
    cookie or an invalid cookie yields the expected 401.
    """
    user = request.user
    if not isinstance(user, Staff):  # pragma: no cover - CookieJWTAuth guarantees Staff
        raise AuthenticationError
    return user
