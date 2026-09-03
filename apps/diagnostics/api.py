"""Session-replay capture, playback and frontend error reporting.

Paths and operationIds are the stable contract:

- POST recordings/                     session_replay_recordings_create      (any staff, own)
- GET  recordings/                     session_replay_recordings_list        (superuser)
- GET  recordings/{id}/                session_replay_recordings_retrieve    (superuser)
- POST recordings/{id}/chunks/         session_replay_recording_chunks_create   (any staff, own)
- GET  recordings/{id}/events/         session_replay_recording_events_retrieve (superuser)
- POST frontend-errors/                session_replay_frontend_errors_create (any staff)

all under ``/api/session-replays/``.

The split is the point: a staff member may write to their OWN recording and
may read none of them. A replay is an unredacted video of somebody's screen,
so reads are superuser-only — v1 gated the API at office staff but hung the
page behind a superuser route, and the narrower of the two is the access the
business actually had.

Integration wiring (config/api.py): ``api.add_router("/session-replays/", router)``.
"""

import logging
from uuid import UUID

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.core.auth import CookieJWTAuth, SuperuserCookieJWTAuth
from apps.core.errors import AppErrorContext, app_error_for, persist_app_error
from apps.core.models import CompanyDefaults
from apps.core.pagination import paginate
from apps.diagnostics.models import SessionReplayRecording
from apps.diagnostics.schemas import (
    ChunkCreateIn,
    ChunkOut,
    FrontendErrorIn,
    FrontendErrorOut,
    PaginatedRecordingList,
    RecordingCreateIn,
    RecordingEventsOut,
    RecordingFiltersIn,
    RecordingOut,
)
from apps.diagnostics.services import session_replay_service as replays

logger = logging.getLogger(__name__)

router = Router(tags=["session-replays"])
auth = CookieJWTAuth()
admin_auth = SuperuserCookieJWTAuth()


def _staff(request: HttpRequest) -> Staff:
    """Narrow the authenticated user to a real Staff row (ADR 0028)."""
    user = request.user
    if not isinstance(user, Staff):  # pragma: no cover - CookieJWTAuth guarantees Staff
        raise HttpError(401, "Authentication credentials were not provided.")
    return user


def _own_recording(request: HttpRequest, recording_id: UUID) -> SessionReplayRecording:
    """Return the caller's own recording, or raise a 404.

    404 rather than 403 on someone else's recording: a 403 would confirm that
    the id exists, which is more than a client uploading to its own session
    needs to know.
    """
    return get_object_or_404(SessionReplayRecording, id=recording_id, user=_staff(request))


def _recording_out(recording: SessionReplayRecording) -> dict[str, object]:
    """Flatten a recording for the wire, including the owner's email."""
    return {
        "payload_available": replays.has_payloads(recording),
        "id": recording.id,
        "user_id": recording.user_id,
        "user_email": recording.user.office_email,
        "started_at": recording.started_at,
        "last_seen_at": recording.last_seen_at,
        "ended_at": recording.ended_at,
        "initial_path": recording.initial_path,
        "latest_path": recording.latest_path,
        "job_id": recording.job_id,
        "viewport_width": recording.viewport_width,
        "viewport_height": recording.viewport_height,
        "event_count": recording.event_count,
        "compressed_bytes": recording.compressed_bytes,
    }


@router.post(
    "/recordings/",
    auth=auth,
    operation_id="session_replay_recordings_create",
    response={201: RecordingOut},
    summary="Open a session replay recording",
)
def session_replay_recordings_create(
    request: HttpRequest, payload: RecordingCreateIn
) -> Status[dict[str, object]]:
    """Open a recording owned by the caller."""
    if not CompanyDefaults.get_solo().session_replay_enabled:
        raise HttpError(409, "Session replay is disabled for this company.")

    recording = replays.create_recording(
        replays.NewRecording(
            user=_staff(request),
            initial_path=payload.initial_path,
            user_agent=request.headers.get("User-Agent") or None,
            viewport=replays.Viewport(width=payload.viewport_width, height=payload.viewport_height),
            job_id=payload.job_id,
        )
    )
    return Status(201, _recording_out(recording))


@router.post(
    "/recordings/{recording_id}/chunks/",
    auth=auth,
    operation_id="session_replay_recording_chunks_create",
    response={201: ChunkOut},
    summary="Upload a batch of replay events",
)
def session_replay_recording_chunks_create(
    request: HttpRequest, recording_id: UUID, payload: ChunkCreateIn
) -> Status[dict[str, object]]:
    """Store one batch of events against the caller's own recording."""
    recording = _own_recording(request, recording_id)
    if recording.chunks.filter(sequence=payload.sequence).exists():
        # 409, not 400: the client's retry loop treats this as "already
        # landed, move on" rather than discarding the recording.
        raise HttpError(409, f"Chunk {payload.sequence} already stored.")

    chunk = replays.append_chunk(
        replays.NewChunk(
            recording=recording,
            sequence=payload.sequence,
            events_json=payload.events_json,
            first_event_timestamp_ms=payload.first_event_timestamp_ms,
            last_event_timestamp_ms=payload.last_event_timestamp_ms,
            path=payload.path,
            viewport=replays.Viewport(width=payload.viewport_width, height=payload.viewport_height),
            job_id=payload.job_id,
        )
    )
    return Status(
        201,
        {
            "id": chunk.id,
            "recording_id": chunk.recording_id,
            "sequence": chunk.sequence,
            "event_count": chunk.event_count,
            "compressed_bytes": chunk.compressed_bytes,
        },
    )


@router.get(
    "/recordings/",
    auth=admin_auth,
    operation_id="session_replay_recordings_list",
    response=PaginatedRecordingList,
    summary="List session replay recordings",
)
def session_replay_recordings_list(
    request: HttpRequest,
    filters: Query[RecordingFiltersIn],
    page: int = 1,
    page_size: int | None = None,
) -> dict[str, object]:
    """Return a page of recordings, newest first."""
    narrowing = replays.RecordingFilters(
        user_id=filters.user_id,
        job_id=filters.job_id,
        started_after=filters.started_after,
        started_before=filters.started_before,
    )
    page_data = paginate(replays.recordings_queryset(narrowing), page=page, page_size=page_size)
    return {
        "results": [_recording_out(recording) for recording in page_data.rows],
        "count": page_data.count,
        "page": page_data.page,
        "page_size": page_data.page_size,
        "total_pages": page_data.total_pages,
    }


@router.get(
    "/recordings/{recording_id}/",
    auth=admin_auth,
    operation_id="session_replay_recordings_retrieve",
    response=RecordingOut,
    summary="Retrieve one session replay recording",
)
def session_replay_recordings_retrieve(
    request: HttpRequest, recording_id: UUID
) -> dict[str, object]:
    """Return one recording's metadata."""
    recording = get_object_or_404(
        SessionReplayRecording.objects.select_related("user"), id=recording_id
    )
    return _recording_out(recording)


@router.get(
    "/recordings/{recording_id}/events/",
    auth=admin_auth,
    operation_id="session_replay_recording_events_retrieve",
    response=RecordingEventsOut,
    summary="Retrieve a recording's events for playback",
)
def session_replay_recording_events_retrieve(
    request: HttpRequest, recording_id: UUID
) -> dict[str, object]:
    """Return every event of a recording, in playback order."""
    recording = get_object_or_404(SessionReplayRecording, id=recording_id)
    try:
        events = replays.recording_events(recording)
    except replays.ReplayPayloadMissingError as exc:
        # 409, not 500: the rows are intact and the request is well formed —
        # this environment simply does not hold the payloads, which no amount
        # of retrying from this machine will change. The envelope persists an
        # AppError for an HttpError too (envelope.py), so this does not save a
        # row; what it buys is a caller who is told what to do instead of
        # meeting "Unexpected server error" and a traceback.
        raise HttpError(
            409,
            "This recording's events are not on this machine. Recording and chunk "
            "rows travel inside a database restore; the payloads only arrive with "
            "scripts/ops/pull_prod_files.sh.",
        ) from exc
    return {"recording_id": recording.id, "events": events}


@router.post(
    "/frontend-errors/",
    auth=auth,
    operation_id="session_replay_frontend_errors_create",
    response={201: FrontendErrorOut},
    summary="Report an uncaught browser error",
)
def session_replay_frontend_errors_create(
    request: HttpRequest, payload: FrontendErrorIn
) -> Status[dict[str, object]]:
    """Persist a browser-side failure, linked to the replay it happened in.

    The exception is constructed here rather than raised: the failure already
    happened in the browser, and this endpoint's job is to file it, not to
    fail. ``persist_app_error`` validates the replay id and demotes one that
    is not the caller's into the error's data.
    """
    staff = _staff(request)
    reported = RuntimeError(payload.message)
    persist_app_error(
        reported,
        AppErrorContext(
            app="frontend",
            file=payload.path,
            user_id=staff.pk,
            session_replay_id=payload.session_replay_id,
            additional_context={
                "source": "frontend",
                "stack": payload.stack,
                "path": payload.path,
            },
        ),
    )
    app_error = app_error_for(reported)
    return Status(201, {"error_id": app_error.id if app_error is not None else None})
