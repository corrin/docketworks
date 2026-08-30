"""Ninja exception handlers producing the standard error envelope.

Authenticated failures use ``{"detail": <message>, "error_id": <AppError
uuid>}``; public failures mask exception text. Expected auth refusals instead
carry ``code`` plus ``error_id: null`` and never create an AppError row. ADRs
0013, 0019 and 0038 define that internet-facing boundary.

Status mapping:

- not authenticated            -> 401 ``authentication_required`` auth envelope
- invalid application input    -> 400, message verbatim
- application access denied    -> 403, message verbatim
- application state conflict   -> 409, message verbatim
- OCC precondition failed      -> 412 ``Precondition failed (ETag mismatch)...`` (ADR 0003)
- permission denied            -> 403 ``You do not have permission to perform this action.``
- Http404                      -> 404 ``Not found.``
- ninja HttpError              -> its status code, message verbatim
- request validation           -> 422 with Ninja's native error list
- anything else                -> 500, message verbatim (ADR 0013)
"""

import logging
from functools import partial

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, AuthorizationError, HttpError
from ninja.errors import ValidationError as RequestValidationError

from apps.core.auth import PasswordChangeRequiredError
from apps.core.errors import (
    AccessDeniedError,
    AppErrorContext,
    ApplicationError,
    ConflictError,
    InvalidInputError,
    app_error_for,
    persist_app_error,
)
from apps.core.etag import PreconditionFailedError
from apps.core.schemas import AUTHENTICATION_REQUIRED_DETAIL, auth_error

auth_logger = logging.getLogger("auth")

NOT_AUTHENTICATED_DETAIL = AUTHENTICATION_REQUIRED_DETAIL
PERMISSION_DENIED_DETAIL = "You do not have permission to perform this action."
NOT_FOUND_DETAIL = "Not found."

_APPLICATION_ERROR_STATUSES: tuple[tuple[type[ApplicationError], int], ...] = (
    (InvalidInputError, 400),
    (AccessDeniedError, 403),
    (ConflictError, 409),
)


def _persist_from_request(exc: Exception, request: HttpRequest) -> str | None:
    """Persist the exception with request context and return its error_id.

    ``persist_app_error`` is idempotent (ADR 0001), so an exception already
    persisted deeper in the stack — where the context was richer — keeps its
    original row; ``app_error_for`` then reads that row's id.
    """
    user_id: str | None = None
    user: object = getattr(request, "user", None)
    # isinstance guard rather than truthiness: keeps AnonymousUser and test
    # doubles (ninja's TestClient mocks the request) out of the user_id column.
    if isinstance(user, AbstractBaseUser) and user.is_authenticated:
        user_id = str(user.pk)
    session_replay_id = request.headers.get("X-Session-Replay-Id")
    persist_app_error(
        exc,
        AppErrorContext(
            user_id=user_id,
            session_replay_id=session_replay_id,
            additional_context={
                "request_path": request.path,
                "request_method": request.method,
                "session_replay_id": session_replay_id,
            },
        ),
    )
    app_error = app_error_for(exc)
    return str(app_error.id) if app_error is not None else None


def _has_authenticated_principal(request: HttpRequest) -> bool:
    """Whether Ninja or Django established a principal for this request."""
    user: object = getattr(request, "user", None)
    if isinstance(user, AbstractBaseUser) and user.is_authenticated:
        return True
    # Ninja stores successful non-Django authentication in request.auth. The
    # value only exists after an auth callable has accepted the request.
    return getattr(request, "auth", None) is not None


def _unexpected_detail(request: HttpRequest, exc: Exception) -> str:
    """Keep staff diagnostics transparent without exposing them publicly."""
    if not _has_authenticated_principal(request):
        return "Unexpected server error."
    return str(exc)


def _error_detail(request: HttpRequest, *, status_code: int, detail: str) -> str:
    """Mask arbitrary domain exception text before authentication succeeds."""
    if not _has_authenticated_principal(request):
        public_details = {
            400: "Invalid request.",
            401: NOT_AUTHENTICATED_DETAIL,
            403: PERMISSION_DENIED_DETAIL,
            404: NOT_FOUND_DETAIL,
            409: "Request conflict.",
            412: "Precondition failed.",
            422: "Invalid request.",
        }
        if status_code >= 500:
            return "Unexpected server error."
        if status_code not in public_details:
            return "Request could not be completed."
        return public_details[status_code]
    return detail


def _log_auth_warning(prefix: str, request: HttpRequest, exc: Exception) -> None:
    """Log rejected authentication and authorization consistently."""
    user: object = getattr(request, "user", None)
    user_info = "anonymous"
    if isinstance(user, AbstractBaseUser) and user.is_authenticated:
        user_info = getattr(user, "office_email", None) or str(user.pk)
    access_cookie_present = "access_token" in request.COOKIES
    refresh_cookie_present = "refresh_token" in request.COOKIES
    auth_logger.warning(
        "%s: user=%s endpoint=%s method=%s "
        "access_cookie_present=%s refresh_cookie_present=%s error=%s",
        prefix,
        user_info,
        request.path,
        request.method,
        access_cookie_present,
        refresh_cookie_present,
        exc,
    )


def _application_error_status(exc: ApplicationError) -> int:
    """Return the transport status for the nearest semantic category."""
    for category, status_code in _APPLICATION_ERROR_STATUSES:
        if isinstance(exc, category):
            return status_code
    return 500


def _handle_application_error(
    api: NinjaAPI, request: HttpRequest, exc: ApplicationError
) -> HttpResponse:
    """Persist and render one semantic application refusal."""
    status_code = _application_error_status(exc)
    error_id = _persist_from_request(exc, request)
    return api.create_response(
        request,
        {
            "detail": _error_detail(request, status_code=status_code, detail=str(exc)),
            "error_id": error_id,
        },
        status=status_code,
    )


def _handle_password_change_required(
    api: NinjaAPI, request: HttpRequest, exc: PasswordChangeRequiredError
) -> HttpResponse:
    """Render the typed refusal that locks a flagged session to the change screen."""
    # Expected security outcome (ADR 0013): stable code, no AppError row.
    _log_auth_warning("Password change required", request, exc)
    return api.create_response(
        request,
        {
            "detail": "Password change required.",
            "code": "password_change_required",
            "error_id": None,
        },
        status=403,
    )


def register_exception_handlers(api: NinjaAPI) -> None:
    """Register the standard envelope exception handlers on the given NinjaAPI."""
    api.add_exception_handler(ApplicationError, partial(_handle_application_error, api))
    api.add_exception_handler(
        PasswordChangeRequiredError, partial(_handle_password_change_required, api)
    )

    @api.exception_handler(Exception)
    def handle_unexpected(request: HttpRequest, exc: Exception) -> HttpResponse:
        error_id = _persist_from_request(exc, request)
        return api.create_response(
            request,
            {"detail": _unexpected_detail(request, exc), "error_id": error_id},
            status=500,
        )

    @api.exception_handler(PreconditionFailedError)
    def handle_precondition_failed(
        request: HttpRequest, exc: PreconditionFailedError
    ) -> HttpResponse:
        # ADR 0003: return actionable operator guidance for an ETag mismatch.
        error_id = _persist_from_request(exc, request)
        return api.create_response(
            request,
            {
                "detail": "Precondition failed (ETag mismatch). Reload the job and retry.",
                "error_id": error_id,
            },
            status=412,
        )

    @api.exception_handler(Http404)
    def handle_not_found(request: HttpRequest, exc: Http404) -> HttpResponse:
        error_id = _persist_from_request(exc, request)
        return api.create_response(
            request,
            {"detail": NOT_FOUND_DETAIL, "error_id": error_id},
            status=404,
        )

    @api.exception_handler(HttpError)
    def handle_http_error(request: HttpRequest, exc: HttpError) -> HttpResponse:
        error_id = _persist_from_request(exc, request)
        return api.create_response(
            request,
            {
                "detail": _error_detail(request, status_code=exc.status_code, detail=str(exc)),
                "error_id": error_id,
            },
            status=exc.status_code,
        )

    @api.exception_handler(AuthenticationError)
    def handle_not_authenticated(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
        _log_auth_warning("Authentication rejected", request, exc)
        response = api.create_response(
            request,
            auth_error("authentication_required").model_dump(),
            status=401,
        )
        response["WWW-Authenticate"] = "Cookie"
        return response

    @api.exception_handler(AuthorizationError)
    def handle_not_authorized(request: HttpRequest, exc: AuthorizationError) -> HttpResponse:
        error_id = _persist_from_request(exc, request)
        _log_auth_warning("Permission denied", request, exc)
        # ADR 0038: carry custom PermissionDenied details through;
        # fall back to the standard string for ninja's message-less default.
        message = str(exc)
        detail = message if message and message != "Forbidden" else PERMISSION_DENIED_DETAIL
        return api.create_response(
            request,
            {"detail": detail, "error_id": error_id},
            status=403,
        )

    @api.exception_handler(PermissionDenied)
    def handle_permission_denied(request: HttpRequest, exc: PermissionDenied) -> HttpResponse:
        error_id = _persist_from_request(exc, request)
        _log_auth_warning("Permission denied", request, exc)
        if not _has_authenticated_principal(request):
            detail = PERMISSION_DENIED_DETAIL
        else:
            detail = str(exc) or PERMISSION_DENIED_DETAIL
        return api.create_response(
            request,
            {"detail": detail, "error_id": error_id},
            status=403,
        )

    @api.exception_handler(RequestValidationError)
    def handle_validation_error(request: HttpRequest, exc: RequestValidationError) -> HttpResponse:
        error_id = _persist_from_request(exc, request)
        return api.create_response(
            request,
            {"detail": exc.errors, "error_id": error_id},
            status=422,
        )
