import inspect
import logging
import traceback
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpRequest

from apps.workflow.exceptions import AlreadyLoggedException, XeroValidationError
from apps.workflow.models import AppError, XeroError


def _make_json_serializable(obj: Any) -> Any:
    """Convert non-JSON-serializable objects (like UUIDs) to strings."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    return obj


def _extract_caller_context():
    """Automatically extract context from the calling function."""
    frame = inspect.currentframe()
    try:
        # Go up the call stack: _extract_caller_context -> persist_app_error -> actual caller
        caller_frame = frame.f_back.f_back

        # Get file path and extract relative path from project root
        file_path = Path(caller_frame.f_code.co_filename)

        # Extract app name from path (e.g., apps/workflow/api/xero/sync.py -> workflow)
        parts = file_path.parts
        if "apps" in parts:
            app_index = parts.index("apps")
            if len(parts) > app_index + 1:
                app_name = parts[app_index + 1]
            else:
                app_name = None
        else:
            app_name = None

        # Get relative file path from apps directory
        if "apps" in parts:
            app_index = parts.index("apps")
            relative_file = "/".join(parts[app_index + 1 :])
        else:
            relative_file = file_path.name

        function_name = caller_frame.f_code.co_name

        return {"app": app_name, "file": relative_file, "function": function_name}
    finally:
        del frame


def extract_request_context(request: HttpRequest) -> Dict[str, Any]:
    """Extract context from Django request object."""
    return {
        "user_id": request.user.id if request.user.is_authenticated else None,
        "request_path": request.path,
        "request_method": request.method,
        "session_replay_id": request.headers.get("X-Session-Replay-Id"),
    }


def extract_job_context(job):
    """Extract context from Job object."""
    return {
        "job_id": job.id,
        "entity_type": "Job",
        "entity_id": str(job.id),
        "business_process": "Job Management",
    }


def persist_xero_error(exc: XeroValidationError):
    """Create and save a ``XeroError`` from the given exception."""
    XeroError.objects.create(
        message=str(exc),
        data={"missing_fields": exc.missing_fields},
        entity=exc.entity,
        reference_id=exc.xero_id,
        kind="Xero",
    )


def persist_app_error(
    exception: Exception,
    app: str = None,
    file: str = None,
    function: str = None,
    severity: int = logging.ERROR,
    job_id: str = None,
    user_id: str = None,
    session_replay_id: str = None,
    additional_context: dict = None,
) -> AppError:
    """Create and save an AppError with enhanced context.

    The app, file, and function parameters are automatically extracted from the calling code.
    If the auto-extraction doesn't work correctly, you can override by providing these parameters explicitly.

    Args:
        exception: The exception to persist
        app: App name (auto-extracted from file path if not provided)
        file: File path (auto-extracted from caller if not provided)
        function: Function name (auto-extracted from caller if not provided)
        severity: Logging severity level (default: logging.ERROR)
        job_id: Job UUID for job-related errors
        user_id: User UUID for user-related errors
        session_replay_id: SessionReplayRecording UUID for browser context
        additional_context: Additional context data to store in JSON field

    Returns:
        Created AppError instance
    """
    # Auto-extract caller context if not provided
    caller_context = _extract_caller_context()

    context_data = {"trace": traceback.format_exc()}
    if additional_context:
        context_data.update(_make_json_serializable(additional_context))
        session_replay_id = session_replay_id or additional_context.get(
            "session_replay_id"
        )

    clean_session_replay_id = None
    if session_replay_id:
        try:
            clean_session_replay_id = UUID(str(session_replay_id))
        except ValueError:
            context_data["invalid_session_replay_id"] = str(session_replay_id)

    return AppError.objects.create(
        message=str(exception),
        data=context_data,
        app=app or caller_context["app"],
        file=file or caller_context["file"],
        function=function or caller_context["function"],
        severity=severity,
        job_id=job_id,
        user_id=user_id,
        session_replay_id=clean_session_replay_id,
    )


def list_app_errors(
    *,
    limit: int = 50,
    offset: int = 0,
    app: str | None = None,
    severity: int | None = None,
    resolved: bool | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """Return paginated AppError records with optional filtering."""
    if limit <= 0:
        limit = 1
    limit = min(limit, 200)
    offset = max(offset, 0)

    queryset: QuerySet[AppError] = AppError.objects.all().order_by("-timestamp")

    if app:
        queryset = queryset.filter(app__icontains=app.strip())
    if severity is not None:
        queryset = queryset.filter(severity=severity)
    if resolved is not None:
        queryset = queryset.filter(resolved=resolved)
    if job_id:
        queryset = queryset.filter(job_id=job_id)
    if user_id:
        queryset = queryset.filter(user_id=user_id)

    total = queryset.count()
    results = list(queryset[offset : offset + limit])

    next_offset: str | None = None
    prev_offset: str | None = None
    if offset + limit < total:
        next_offset = str(offset + limit)
    if offset > 0:
        prev_offset = str(max(offset - limit, 0))

    return {
        "count": total,
        "next": next_offset,
        "previous": prev_offset,
        "results": results,
    }


def persist_and_raise(exception: Exception, **context: Any) -> None:
    """
    Persist the exception via ``persist_app_error`` and raise AlreadyLoggedException.

    Args:
        exception: The original exception to persist.
        context: Additional keyword arguments forwarded to ``persist_app_error``.
    """
    app_error = persist_app_error(exception, **context)
    raise AlreadyLoggedException(exception, app_error.id)
