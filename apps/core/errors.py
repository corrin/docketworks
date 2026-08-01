"""Error persistence: every exception becomes exactly one ``AppError`` row.

Ported from v1 ``apps/workflow/services/error_persistence.py`` with verbatim
semantics (ADR 0019: every ``except`` block persists; ADR 0001: idempotent
marking, one row per failure no matter how many handlers catch it).

Not ported here: ``persist_xero_error`` (xero app), ``extract_job_context``
(job app), ``list_app_errors`` (diagnostics error browsing) — each belongs to
an app above core in the layer contract and moves with its owner.
"""

import inspect
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast
from uuid import UUID

from django.apps import apps as django_apps

from apps.core.models import AppError

# Set on an exception instance once it has been persisted. BaseException always
# carries a __dict__, so this is safe to set on any exception. The marker is
# metadata *about* the exception, deliberately not a wrapper type — wrapping
# would destroy the type the HTTP boundary needs to choose a status code.
_APP_ERROR_ATTR = "__app_error__"


class _CallerContext(TypedDict):
    """Code location auto-extracted from the frame that called persist_app_error."""

    app: str | None
    file: str | None
    function: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class AppErrorContext:
    """Optional context accompanying a persisted exception.

    ``app``/``file``/``function`` override the location auto-extracted from the
    calling frame; the id fields link the row to a job, user, or session
    replay; ``additional_context`` lands in the AppError JSON data field.
    """

    app: str | None = None
    file: str | None = None
    function: str | None = None
    severity: int = logging.ERROR
    job_id: str | UUID | None = None
    user_id: str | UUID | None = None
    session_replay_id: str | UUID | None = None
    additional_context: dict[str, object] | None = None


def _mark_persisted(exception: Exception, app_error: AppError) -> None:
    setattr(exception, _APP_ERROR_ATTR, app_error)


def _existing_app_error(exception: Exception) -> AppError | None:
    """Find the AppError for this failure, following the ``__cause__`` chain.

    A handler that converts (``raise ValueError(...) from exc``) produces a new
    exception object, so the marker lives on the cause rather than on what the
    boundary finally sees. Walking the chain keeps one failure to one row across
    conversions. This is why ``raise ... from exc`` is mandatory (pylint W0707) —
    an unchained conversion severs the link and earns a second row.
    """
    seen: set[int] = set()
    current: BaseException | None = exception
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        app_error: object = getattr(current, _APP_ERROR_ATTR, None)
        if isinstance(app_error, AppError):
            return app_error
        current = current.__cause__
    return None


def _make_json_serializable(obj: object) -> object:
    """Convert non-JSON-serializable objects (like UUIDs) to strings."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_make_json_serializable(item) for item in obj]
    return obj


def _extract_caller_context() -> _CallerContext:
    """Automatically extract context from the calling function."""
    frame = inspect.currentframe()
    try:
        # Go up the call stack: _extract_caller_context -> persist_app_error -> actual caller
        if frame is None or frame.f_back is None or frame.f_back.f_back is None:
            return {"app": None, "file": None, "function": None}
        caller_frame = frame.f_back.f_back

        # Get file path and extract relative path from project root
        file_path = Path(caller_frame.f_code.co_filename)

        # Extract app name from path (e.g., apps/core/errors.py -> core)
        parts = file_path.parts
        if "apps" in parts:
            app_index = parts.index("apps")
            app_name = parts[app_index + 1] if len(parts) > app_index + 1 else None
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


def _clean_session_replay_id(
    *,
    session_replay_id: str | UUID | None,
    user_id: str | UUID | None,
    context_data: dict[str, object],
) -> UUID | None:
    if not session_replay_id:
        return None

    try:
        clean_session_replay_id = UUID(str(session_replay_id))
    except ValueError:
        context_data["invalid_session_replay_id"] = str(session_replay_id)
        return None

    # v1 semantics: verify the id against SessionReplayRecording (scoped to
    # user_id when given) and record unlinked ids in context_data instead of
    # storing them. AppError.session_replay is a live DB FK, so skipping this
    # check would turn an unlinked id into an IntegrityError INSIDE the
    # error-persistence path. Resolved via the app registry because core sits
    # below diagnostics in the layer contract and must not import it.
    recording_model = django_apps.get_model("diagnostics", "SessionReplayRecording")
    queryset = recording_model.objects.filter(id=clean_session_replay_id)
    if user_id:
        try:
            clean_user_id = UUID(str(user_id))
        except ValueError:
            context_data["invalid_user_id_for_session_replay"] = str(user_id)
            return None
        queryset = queryset.filter(user_id=clean_user_id)

    if not queryset.exists():
        context_data["unlinked_session_replay_id"] = str(clean_session_replay_id)
        return None

    return clean_session_replay_id


def persist_app_error(
    exception: Exception,
    context: AppErrorContext | None = None,
) -> AppError:
    """Create and save an AppError row for this exception.

    The code location (app, file, function) is automatically extracted from
    the calling frame; ``context`` overrides it and carries the optional
    severity, linkage ids, and free-form JSON context (see AppErrorContext).

    Returns:
        The AppError for this exception — newly created, or the existing one
        if it has already been persisted.
    """
    already_persisted = _existing_app_error(exception)
    if already_persisted is not None:
        # Persisted deeper in the stack, where the context was richer. One
        # failure is one row; the first write wins.
        return already_persisted

    ctx = context if context is not None else AppErrorContext()

    # Auto-extract caller context if not provided
    caller_context = _extract_caller_context()

    context_data: dict[str, object] = {"trace": traceback.format_exc()}
    session_replay_id = ctx.session_replay_id
    if ctx.additional_context:
        serializable = _make_json_serializable(dict(ctx.additional_context))
        context_data.update(cast("dict[str, object]", serializable))
        if not session_replay_id:
            raw_replay_id = ctx.additional_context.get("session_replay_id")
            session_replay_id = str(raw_replay_id) if raw_replay_id is not None else None

    clean_session_replay_id = _clean_session_replay_id(
        session_replay_id=session_replay_id,
        user_id=ctx.user_id,
        context_data=context_data,
    )

    app_error = AppError.objects.create(
        message=str(exception),
        data=context_data,
        app=ctx.app or caller_context["app"],
        file=ctx.file or caller_context["file"],
        function=ctx.function or caller_context["function"],
        severity=ctx.severity,
        job_id=ctx.job_id,
        user_id=ctx.user_id,
        session_replay_id=clean_session_replay_id,
    )
    _mark_persisted(exception, app_error)
    return app_error


def app_error_for(exception: Exception) -> AppError | None:
    """Return the AppError this exception was persisted as, if any.

    Response builders use this to surface ``error_id`` (ADR 0013) without
    needing the exception to have been wrapped in a marker type.
    """
    return _existing_app_error(exception)
