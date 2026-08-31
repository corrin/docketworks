"""Authentication and user-profile endpoints.

Paths and operationIds are the stable contract:

- POST /api/accounts/token/          accounts_token_create          (login)
- POST /api/accounts/token/refresh/  accounts_token_refresh_create
- POST /api/accounts/logout/         accounts_logout_create
- GET  /api/accounts/me/             accounts_me_retrieve
- POST /api/accounts/me/password/    accounts_me_password_create    (authenticated)
- POST /api/accounts/password-reset/          accounts_password_reset_create         (anonymous)
- POST /api/accounts/password-reset/confirm/  accounts_password_reset_confirm_create (anonymous)
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

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
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
    PasswordErrorOut,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
    PasswordResetResponse,
    StaffCreateIn,
    StaffListItemOut,
    StaffUpdateIn,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserProfile,
)
from apps.accounts.staff_directory import get_displayable_staff, list_all_staff
from apps.accounts.tasks import send_password_reset_email_task
from apps.core.auth import (
    CookieJWTAuth,
    SuperuserCookieJWTAuth,
    clear_auth_cookies,
    issue_refresh_token,
    jwt_cookie_config,
    set_access_cookie,
    set_refresh_cookie,
    token_fingerprint_is_current,
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
    refresh = issue_refresh_token(user)
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
    if not token_fingerprint_is_current(refresh, user):
        # A refresh token minted before the last password change must not
        # keep minting access tokens — it is exactly the credential a
        # change/reset exists to evict. Deliberately NO cookie clear here:
        # a request racing a successful self-service change can land this
        # 401 AFTER the change response set fresh cookies, and a clear
        # would delete the session the changer was just re-minted.
        logger.info("JWT REFRESH FAILURE - stale password fingerprint pk=%s", user.pk)
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
    response={200: PasswordChangeResponse, 400: PasswordErrorOut, 401: AuthErrorOut},
    summary="Change the authenticated user's own password",
)
def accounts_me_password_create(
    request: HttpRequest, response: HttpResponse, payload: PasswordChangeRequest
) -> Status[PasswordChangeResponse | PasswordErrorOut]:
    """Verify the current password, then validate and set the new one.

    The one self-service credential write. _set_staff_password also clears
    password_needs_reset, which is what releases a flagged session from the
    auth-layer password gate (apps/core/auth.py). Refusals are declared 400
    bodies, not HttpErrors — the wire contract carries their shape, and an
    expected refusal writes no AppError row.
    """
    user = request.user
    if not isinstance(user, Staff):  # pragma: no cover - CookieJWTAuth guarantees Staff
        raise AuthenticationError
    if not user.check_password(payload.current_password):
        # ADR 0038: transparent after authentication — a wrong current
        # password here is the caller's error to fix, not an authentication
        # event, so it is a 400 with the real reason rather than a 401.
        return Status(400, PasswordErrorOut(detail="Current password is incorrect."))
    if payload.new_password == payload.current_password:
        # A forced change satisfied by re-entering the admin-issued temp
        # password would leave the account on a credential someone else
        # knows — the exact state the password_needs_reset gate exists to
        # end.
        return Status(
            400, PasswordErrorOut(detail="The new password must be different from the current one.")
        )
    try:
        _set_staff_password(user, payload.new_password)
    # deliberate-swallow: the self-service change returns the validator's
    # refusal as its declared 400 — an expected weak-password rejection must
    # not write an AppError row the way a raised HttpError would.
    except HttpError as exc:
        return Status(400, PasswordErrorOut(detail=str(exc)))
    # update_fields skips Staff.save()'s wage recompute (nothing wage-related
    # changes) and must name updated_at, which save() assigns manually.
    user.save(update_fields=["password", "password_needs_reset", "updated_at"])
    # Every issued token carries the password fingerprint, so this change
    # just killed the caller's own cookies too; re-minting here keeps the
    # changer signed in while every other session's tokens die.
    refresh = issue_refresh_token(user)
    set_access_cookie(response, str(refresh.access_token))
    set_refresh_cookie(response, str(refresh))
    logger.info("PASSWORD CHANGED - pk=%s", user.pk)
    return Status(200, PasswordChangeResponse())


INVALID_RESET_LINK_DETAIL = "This reset link is invalid or has expired."


def _stored_email_matching(staff: Staff, normalized: str) -> str:
    """Return the stored email column the submitted address matched.

    The stored value, not the submitted string: the emailed copy should carry
    the canonical casing the row holds, and matching it here means a payroll
    address gets its reset at the payroll mailbox.
    """
    lowered = normalized.lower()
    if staff.office_email is not None and staff.office_email.lower() == lowered:
        return staff.office_email
    if staff.payroll_email is not None and staff.payroll_email.lower() == lowered:
        return staff.payroll_email
    raise ValueError(
        "The matched staff row holds neither submitted email; filter and resolution disagree."
    )


@router.post(
    "/password-reset/",
    auth=None,
    operation_id="accounts_password_reset_create",
    response={200: PasswordResetResponse},
    summary="Request a password-reset email",
)
def accounts_password_reset_create(
    request: HttpRequest, payload: PasswordResetRequest
) -> PasswordResetResponse:
    """Email a reset link to the address, if an active account holds it.

    Fixed 200 either way: the anonymous contract must not reveal which
    addresses have accounts (ADR 0038's public contract). The send is
    QUEUED, not made in-request — a synchronous Gmail round trip runs only
    for addresses with accounts, which makes response latency (and a Gmail
    outage's 500) an account-existence oracle; the enqueue costs the same
    either way. The match is the login backend's own (sole_login_match), so
    anyone who can sign in can reset.
    """
    staff = Staff.objects.sole_login_match(payload.email)
    if staff is None or not staff.is_currently_active:
        logger.info("PASSWORD RESET REQUESTED - no single active account for the submitted email")
        return PasswordResetResponse()
    recipient = _stored_email_matching(staff, Staff.objects.normalize_email(payload.email).strip())
    uid = urlsafe_base64_encode(force_bytes(staff.pk))
    token = default_token_generator.make_token(staff)
    # Fable: host pinned to settings.APP_DOMAIN, NOT request.build_absolute_uri
    # — ALLOWED_HOSTS also accepts localhost, and USE_X_FORWARDED_HOST means an
    # anonymous caller could poison the victim's genuine reset email with a
    # dead localhost link via X-Forwarded-Host.
    scheme = "https" if request.is_secure() else "http"
    link = f"{scheme}://{settings.APP_DOMAIN}/reset-password?uid={uid}&token={token}"
    send_password_reset_email_task.delay(recipient=recipient, link=link)
    logger.info("PASSWORD RESET EMAIL QUEUED - pk=%s", staff.pk)
    return PasswordResetResponse()


@router.post(
    "/password-reset/confirm/",
    auth=None,
    operation_id="accounts_password_reset_confirm_create",
    response={200: PasswordResetConfirmResponse, 400: PasswordErrorOut},
    summary="Set a new password from a reset link",
)
def accounts_password_reset_confirm_create(
    request: HttpRequest, payload: PasswordResetConfirmRequest
) -> Status[PasswordResetConfirmResponse | PasswordErrorOut]:
    """Exchange a valid uid/token pair for a new password.

    The token hashes the current password (Django's generator), so a
    successful reset burns the link. Refusals are declared 400 bodies, not
    HttpErrors — see PasswordErrorOut.
    """
    try:
        staff = Staff.objects.get(pk=force_str(urlsafe_base64_decode(payload.uid)))
    # deliberate-swallow: a garbled uid must be indistinguishable from an
    # unknown one — both are the fixed invalid-link refusal (ValueError also
    # covers UnicodeDecodeError: valid base64 decoding to invalid UTF-8).
    except (ValueError, DjangoValidationError, Staff.DoesNotExist):
        logger.info("PASSWORD RESET CONFIRM REFUSED - undecodable or unknown uid")
        return Status(400, PasswordErrorOut(detail=INVALID_RESET_LINK_DETAIL))
    if not staff.is_currently_active or not default_token_generator.check_token(
        staff, payload.token
    ):
        logger.info("PASSWORD RESET CONFIRM REFUSED - pk=%s", staff.pk)
        return Status(400, PasswordErrorOut(detail=INVALID_RESET_LINK_DETAIL))
    try:
        _set_staff_password(staff, payload.new_password)
    # deliberate-swallow: the ANONYMOUS confirm cannot raise — the envelope
    # masks pre-auth HttpError text (ADR 0038), and the validator's reason is
    # exactly what the reset-link holder must read.
    except HttpError as exc:
        return Status(400, PasswordErrorOut(detail=str(exc)))
    staff.save(update_fields=["password", "password_needs_reset", "updated_at"])
    logger.info("PASSWORD RESET COMPLETE - pk=%s", staff.pk)
    return Status(200, PasswordResetConfirmResponse())


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

    Fable: the one set-password surface: validate_password runs
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
    if payload.password_needs_reset:
        # Fable: an admin may issue a known temporary password and force its
        # change; the explicit flag outlives _set_staff_password's clear.
        staff.password_needs_reset = True
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
