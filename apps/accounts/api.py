"""Authentication and user-profile endpoints.

Paths and operationIds are the stable contract:

- POST /api/accounts/token/          accounts_token_create          (login)
- POST /api/accounts/token/refresh/  accounts_token_refresh_create
- POST /api/accounts/logout/         accounts_logout_create
- GET  /api/accounts/me/             accounts_me_retrieve
- POST /api/accounts/me/password/    accounts_me_password_create    (authenticated)
- GET  /api/accounts/staff/          accounts_staff_list            (superuser)
- POST /api/accounts/staff/          accounts_staff_create          (superuser)
- PATCH /api/accounts/staff/{staff_id}/    accounts_staff_partial_update  (superuser)
- POST /api/accounts/staff/{staff_id}/icon/   accounts_staff_icon_create  (superuser)
- DELETE /api/accounts/staff/{staff_id}/icon/ accounts_staff_icon_destroy (superuser)
- GET  /api/accounts/staff/all/      accounts_staff_all_list        (authenticated)

Integration wiring (config/api.py): ``api.add_router("/accounts/", router)``.
"""

import logging
from uuid import UUID

from django.contrib.auth import authenticate
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import File, Query, Router
from ninja.errors import AuthenticationError, HttpError
from ninja.files import UploadedFile
from ninja.responses import Status
from ninja_jwt.exceptions import TokenError
from ninja_jwt.settings import api_settings
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import STAFF_MANAGER_GROUP_NAME, Staff
from apps.accounts.schemas import (
    KanbanStaffOut,
    KanbanStaffQuery,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    StaffCreateIn,
    StaffListItemOut,
    StaffUpdateIn,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserProfile,
)
from apps.accounts.staff_directory import get_displayable_staff, list_all_staff
from apps.core.auth import (
    CookieJWTAuth,
    SuperuserCookieJWTAuth,
    clear_auth_cookies,
    jwt_cookie_config,
    set_access_cookie,
    set_refresh_cookie,
)
from apps.core.schemas import AuthErrorOut, auth_error
from apps.core.uploads import delete_stored_image, validate_image_upload

logger = logging.getLogger(__name__)

router = Router(tags=["accounts"])


@router.post(
    "/token/",
    auth=None,
    operation_id="accounts_token_create",
    response={200: LoginResponse, 401: AuthErrorOut},
    summary="Obtain JWT tokens as HttpOnly cookies (login)",
)
def login(
    request: HttpRequest, response: HttpResponse, payload: LoginRequest
) -> Status[LoginResponse | AuthErrorOut]:
    """Authenticate and set the JWT cookies.

    Authenticates username(=email)/password, sets access+refresh HttpOnly
    cookies, and returns an empty body (plus password_needs_reset when the
    user must change their password).
    """
    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None or not isinstance(user, Staff):
        logger.warning("JWT LOGIN FAILURE - invalid credentials")
        return Status(401, auth_error("invalid_credentials"))
    if not user.is_currently_active:
        # Departed staff must be rejected at login, not merely on
        # follow-up requests — otherwise valid cookies + per-request 401s
        # trap them in a silent login/redirect loop.
        logger.warning("JWT LOGIN REJECTED - inactive user pk=%s", user.pk)
        return Status(401, auth_error("invalid_credentials"))
    refresh = RefreshToken.for_user(user)
    set_access_cookie(response, str(refresh.access_token))
    set_refresh_cookie(response, str(refresh))
    logger.info("JWT LOGIN SUCCESS - username=%s", payload.username)
    if user.password_needs_reset:
        logger.info("User %s needs password reset", payload.username)
        return Status(200, LoginResponse(password_needs_reset=True))
    return Status(200, LoginResponse())


@router.post(
    "/token/refresh/",
    auth=None,
    operation_id="accounts_token_refresh_create",
    response={200: TokenRefreshResponse, 401: AuthErrorOut},
    summary="Refresh the access-token cookie from the refresh token",
)
def token_refresh(
    request: HttpRequest,
    response: HttpResponse,
    payload: TokenRefreshRequest | None = None,
) -> Status[TokenRefreshResponse | AuthErrorOut]:
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
        clear_auth_cookies(response)
        return Status(401, auth_error("authentication_required"))
    try:
        refresh = RefreshToken(raw_refresh)
    # deliberate-swallow: an invalid refresh token is not re-raised — browsers
    # retain expired or replaced cookies, so the required outcome is clearing
    # the unusable credential and returning the fixed anonymous 401 contract.
    except TokenError as exc:
        logger.info("JWT REFRESH FAILURE - invalid refresh token: %s", exc)
        # Clearing the unusable credential is the complete security outcome.
        clear_auth_cookies(response)
        return Status(401, auth_error("authentication_required"))

    try:
        user_id = UUID(str(refresh[api_settings.USER_ID_CLAIM]))
        user = Staff.objects.get(pk=user_id)
    # deliberate-swallow: a token whose Staff identity is malformed or gone is
    # not re-raised — a Staff record can disappear after token issue, so the
    # required outcome is clearing the credential and returning the fixed
    # anonymous 401 contract.
    except (KeyError, ValueError, DjangoValidationError, Staff.DoesNotExist):
        logger.info("JWT REFRESH FAILURE - token user is unavailable")
        clear_auth_cookies(response)
        return Status(401, auth_error("authentication_required"))
    if not user.is_currently_active:
        logger.info("JWT REFRESH FAILURE - inactive user pk=%s", user.pk)
        clear_auth_cookies(response)
        return Status(401, auth_error("authentication_required"))
    set_access_cookie(response, str(refresh.access_token))
    return Status(200, TokenRefreshResponse())


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
    # 401 is produced by the auth layer, not this handler; declaring it
    # here puts the expected session-probe refusal in the OpenAPI contract.
    response={200: UserProfile, 401: AuthErrorOut},
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


@router.post(
    "/me/password/",
    auth=CookieJWTAuth(),
    operation_id="accounts_me_password_create",
    response={200: PasswordChangeResponse, 401: AuthErrorOut},
    summary="Change the authenticated user's own password",
)
def accounts_me_password_create(
    request: HttpRequest, payload: PasswordChangeRequest
) -> PasswordChangeResponse:
    """Verify the current password, then validate and set the new one.

    The one self-service credential write. _set_staff_password also clears
    password_needs_reset, which is what releases a flagged session from the
    auth-layer password gate (apps/core/auth.py).
    """
    user = request.user
    if not isinstance(user, Staff):  # pragma: no cover - CookieJWTAuth guarantees Staff
        raise AuthenticationError
    if not user.check_password(payload.current_password):
        # ADR 0038: transparent after authentication — a wrong current
        # password here is the caller's error to fix, not an authentication
        # event, so it is a 400 with the real reason rather than a 401.
        raise HttpError(400, "Current password is incorrect.")
    _set_staff_password(user, payload.new_password)
    # update_fields skips Staff.save()'s wage recompute (nothing wage-related
    # changes) and must name updated_at, which save() assigns manually.
    user.save(update_fields=["password", "password_needs_reset", "updated_at"])
    logger.info("PASSWORD CHANGED - pk=%s", user.pk)
    return PasswordChangeResponse()


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


# ── Staff admin writes ───────────────────────────────────────────────────
#
# Fable: Superuser on every verb, like the list — v1 gated these on
# is_office_staff while its UI required superuser, so any office member could
# PATCH is_superuser onto themselves. There is deliberately no DELETE for the
# staff row itself: offboarding is date_left (time entries PROTECT the row),
# and clearing date_left reinstates.


def _apply_staff_fields(staff: Staff, supplied: dict[str, object]) -> Staff:
    """Setattr the JSON fields, validate, and fully save.

    Fable: A full save, never update_fields — Staff.save() computes wage_rate
    and the default labour subtype only when update_fields is None or names
    base_wage_rate, so a partial save would compute the new wage_rate and then
    not persist it.
    """
    for field, value in supplied.items():
        setattr(staff, field, value)
    try:
        staff.full_clean()
    except DjangoValidationError as exc:
        # Converted rather than left to escape: an unhandled model
        # ValidationError is a 500, and a rejected staff value (a duplicate
        # email included — unique checks run in full_clean) is the caller's to
        # fix. Same flattening as company_defaults_partial_update.
        raise HttpError(400, "; ".join(exc.messages)) from exc
    staff.save()
    return staff


def _set_staff_password(staff: Staff, password: str) -> None:
    """Validate and hash a new password onto the unsaved staff row.

    The one set-password surface: validate_password runs
    AUTH_PASSWORD_VALIDATORS, and a fresh password clears
    password_needs_reset — nothing else ever clears the flag the
    flag_weak_passwords sweep and the scrubber set.
    """
    try:
        validate_password(password, staff)
    except DjangoValidationError as exc:
        raise HttpError(400, "; ".join(exc.messages)) from exc
    staff.set_password(password)
    staff.password_needs_reset = False


def _set_staff_manager(staff: Staff, is_member: bool) -> None:
    """Add or remove StaffManager membership to match the checkbox."""
    # get_or_create, not get: nothing seeds the group — it exists because a
    # staff member was first made a manager.
    group, _ = Group.objects.get_or_create(name=STAFF_MANAGER_GROUP_NAME)
    if is_member:
        staff.groups.add(group)
    else:
        staff.groups.remove(group)


@router.post(
    "/staff/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="accounts_staff_create",
    response={201: StaffListItemOut},
    summary="Create a staff member",
)
def accounts_staff_create(request: HttpRequest, payload: StaffCreateIn) -> Status[Staff]:
    """Create a staff member; omitted fields take the model defaults.

    The password is hashed via set_password and never logged. wage_rate is
    absent from the schema — it derives from base_wage_rate on save.
    """
    # Read password/is_staff_manager off the typed payload, not the dump —
    # str()/bool() around a dict value would be silent coercion (ADR 0028).
    supplied = payload.model_dump(exclude_unset=True)
    supplied.pop("password")
    supplied.pop("is_staff_manager", None)
    staff = Staff(**supplied)
    _set_staff_password(staff, payload.password)
    with transaction.atomic():
        _apply_staff_fields(staff, {})
        if payload.is_staff_manager:
            _set_staff_manager(staff, True)
    return Status(201, staff)


@router.patch(
    "/staff/{uuid:staff_id}/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="accounts_staff_partial_update",
    response=StaffListItemOut,
    summary="Update some fields of a staff member",
)
def accounts_staff_partial_update(
    request: HttpRequest, staff_id: UUID, payload: StaffUpdateIn
) -> Staff:
    """Apply only the fields the caller sent; omission leaves values alone."""
    staff = get_object_or_404(Staff, pk=staff_id)
    # Presence from model_fields_set, values from the typed payload — never
    # str()/bool() around a dump's object values (ADR 0028).
    supplied = payload.model_dump(exclude_unset=True)
    supplied.pop("password", None)
    supplied.pop("is_staff_manager", None)
    if "password" in payload.model_fields_set:
        _set_staff_password(staff, payload.password)
    with transaction.atomic():
        _apply_staff_fields(staff, supplied)
        if "is_staff_manager" in payload.model_fields_set:
            _set_staff_manager(staff, payload.is_staff_manager)
    return staff


@router.post(
    "/staff/{uuid:staff_id}/icon/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="accounts_staff_icon_create",
    response=StaffListItemOut,
    summary="Upload a staff profile icon",
)
def accounts_staff_icon_create(
    request: HttpRequest, staff_id: UUID, file: File[UploadedFile]
) -> Staff:
    """Save the uploaded icon and delete the file it replaces."""
    staff = get_object_or_404(Staff, pk=staff_id)
    validate_image_upload(file, label="Profile picture")
    # Save the new file before unlinking the old one — a save failure must not
    # leave the row pointing at a deleted file. update_fields is deliberate
    # here (nothing wage-related changes) and must name updated_at, which
    # save() assigns manually.
    replaced = staff.icon
    staff.icon = file
    staff.save(update_fields=["icon", "updated_at"])
    delete_stored_image(replaced, allowed_prefix="staff_icons")
    return staff


@router.delete(
    "/staff/{uuid:staff_id}/icon/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="accounts_staff_icon_destroy",
    response=StaffListItemOut,
    summary="Remove a staff profile icon",
)
def accounts_staff_icon_destroy(request: HttpRequest, staff_id: UUID) -> Staff:
    """Clear the icon and delete the stored file; idempotent by design.

    The E2E database restore does not clean MEDIA_ROOT, so spec cleanup needs
    this endpoint; it may run against any state, hence 200 either way.
    """
    staff = get_object_or_404(Staff, pk=staff_id)
    removed = staff.icon
    staff.icon = None
    staff.save(update_fields=["icon", "updated_at"])
    delete_stored_image(removed, allowed_prefix="staff_icons")
    return staff


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
        get_displayable_staff(
            target_date=params.date,
            include_inactive=params.include_inactive,
            actual_users=params.actual_users,
        )
    )
