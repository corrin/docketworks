"""Ninja exception handlers producing v1's error envelope.

Envelope shape (v1 DRF boundary, ADR 0013): ``{"detail": <message>,
"error_id": <AppError uuid>}``. Per ADR 0013 the underlying exception message
is returned verbatim (internal tool, every caller is an authenticated
employee) and ``error_id`` cross-references the persisted ``AppError`` row.
Per ADR 0019 every handler persists via ``persist_app_error`` (idempotent,
ADR 0001) before responding.

Status mapping mirrors v1's DRF exception handler:

- not authenticated            -> 401 ``Authentication credentials were not provided.``
- OCC precondition failed      -> 412 ``Precondition failed (ETag mismatch)...`` (ADR 0003)
- permission denied            -> 403 ``You do not have permission to perform this action.``
- Http404                      -> 404 ``Not found.``
- ninja HttpError              -> its status code, message verbatim
- request validation           -> 422 with ninja's error list (v1/DRF used 400 with a
  field dict; the 422 list is ninja's native shape for the generated client —
  recorded in the parity ledger, no external party holds these URLs)
- anything else                -> 500, message verbatim (ADR 0013)
"""

import logging

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, AuthorizationError, HttpError
from ninja.errors import ValidationError as RequestValidationError

from apps.core.errors import AppErrorContext, app_error_for, persist_app_error
from apps.core.etag import PreconditionFailedError

auth_logger = logging.getLogger("auth")

NOT_AUTHENTICATED_DETAIL = "Authentication credentials were not provided."
PERMISSION_DENIED_DETAIL = "You do not have permission to perform this action."
NOT_FOUND_DETAIL = "Not found."


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


def _log_auth_warning(prefix: str, request: HttpRequest, exc: Exception) -> None:
    """Mirror v1's auth logging for rejected authentication/permission."""
    user: object = getattr(request, "user", None)
    user_info = "anonymous"
    if isinstance(user, AbstractBaseUser) and user.is_authenticated:
        user_info = getattr(user, "email", None) or str(user.pk)
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


def register_exception_handlers(api: NinjaAPI) -> None:
    """Register the v1-envelope exception handlers on the given NinjaAPI."""

    @api.exception_handler(Exception)
    def handle_unexpected(request: HttpRequest, exc: Exception) -> HttpResponse:
        # ADR 0038: trusted environment; the verbatim message plus error_id is
        # what makes rapid diagnosis possible.
        error_id = _persist_from_request(exc, request)
        return api.create_response(
            request,
            {"detail": str(exc), "error_id": error_id},
            status=500,
        )

    @api.exception_handler(PreconditionFailedError)
    def handle_precondition_failed(
        request: HttpRequest, exc: PreconditionFailedError
    ) -> HttpResponse:
        # ADR 0003: ETag mismatch on a mutating request. v1's job/PO views
        # returned this exact operator guidance rather than the raw message.
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
            {"detail": str(exc), "error_id": error_id},
            status=exc.status_code,
        )

    @api.exception_handler(AuthenticationError)
    def handle_not_authenticated(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
        error_id = _persist_from_request(exc, request)
        _log_auth_warning("Authentication rejected", request, exc)
        # ADR 0038: carry the specific rejection reason when the auth layer
        # provides one (inactive user, token errors); generic otherwise.
        message = str(exc)
        detail = message if message and message != "Unauthorized" else NOT_AUTHENTICATED_DETAIL
        return api.create_response(
            request,
            {"detail": detail, "error_id": error_id},
            status=401,
        )

    @api.exception_handler(AuthorizationError)
    def handle_not_authorized(request: HttpRequest, exc: AuthorizationError) -> HttpResponse:
        error_id = _persist_from_request(exc, request)
        _log_auth_warning("Permission denied", request, exc)
        # ADR 0038 + v1 parity: carry custom PermissionDenied details through;
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
        # v1/DRF carried a custom message through when one was raised.
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
