"""Authentication and user-profile endpoints.

Paths and operationIds are the stable contract:

- POST /api/accounts/token/          accounts_token_create          (login)
- POST /api/accounts/token/refresh/  accounts_token_refresh_create
- POST /api/accounts/logout/         accounts_logout_create
- GET  /api/accounts/me/             accounts_me_retrieve
- GET  /api/accounts/staff/          accounts_staff_list            (superuser)
- GET  /api/accounts/staff/all/      accounts_staff_all_list        (authenticated)

Integration wiring (config/api.py): ``api.add_router("/accounts/", router)``.
"""

import logging

from django.contrib.auth import authenticate
from django.http import HttpRequest, HttpResponse
from ninja import Query, Router
from ninja.errors import AuthenticationError
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import Staff
from apps.accounts.schemas import (
    KanbanStaffOut,
    KanbanStaffQuery,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    StaffListItemOut,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserProfile,
)
from apps.accounts.staff_directory import get_kanban_staff, list_all_staff
from apps.core.auth import (
    CookieJWTAuth,
    SuperuserCookieJWTAuth,
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


@router.get(
    "/staff/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="accounts_staff_list",
    response=list[StaffListItemOut],
    summary="The staff admin list, departed members included",
)
def accounts_staff_list(request: HttpRequest) -> list[Staff]:
    """List every staff member with their wage configuration.

    Superuser only: wage_rate/base_wage_rate are pay data, the same
    sensitivity rule as the timesheet management surface.
    """
    return list(list_all_staff())


@router.get(
    "/staff/all/",
    auth=CookieJWTAuth(),
    operation_id="accounts_staff_all_list",
    response=list[KanbanStaffOut],
    summary="The kanban board's staff panel — every authenticated user",
)
def accounts_staff_all_list(request: HttpRequest, params: Query[KanbanStaffQuery]) -> list[Staff]:
    """List staff for the kanban board's staff panel.

    Plain authenticated (not superuser-gated): unlike ``accounts_staff_list``
    this exposes no wage data. ``date`` picks staff active on that date;
    otherwise ``include_inactive`` chooses between all staff and only
    currently-active staff. ``actual_users`` additionally drops staff without
    a valid Xero payroll id.
    """
    return list(
        get_kanban_staff(
            target_date=params.date,
            include_inactive=params.include_inactive,
            actual_users=params.actual_users,
        )
    )
