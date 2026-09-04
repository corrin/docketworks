"""Wire contracts for the session-replay endpoints.

``storage_path`` and ``sha256`` are deliberately absent from every response:
they describe where a payload sits on the server's disk and are of no use to a
client that receives the events themselves.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import Field, Schema
from pydantic import StringConstraints

from apps.core.schemas import NonBlankText, ResponseSchema
from apps.diagnostics.services.session_replay_service import ReplayEvent


class ViewportIn(Schema):
    """Browser viewport, omitted by clients that cannot report one."""

    viewport_width: int | None = None
    viewport_height: int | None = None


# Opus: The columns behind these are CharField(max_length=500) and a captured path
# carries the search string and hash, so an unbounded field here turns a long
# but ordinary URL into a DataError 500 and an AppError row instead of a 422 at
# the boundary.
CapturedPath = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class RecordingCreateIn(ViewportIn):
    """Open a recording for the calling user."""

    initial_path: CapturedPath
    job_id: UUID | None = None


class ChunkCreateIn(ViewportIn):
    """One batch of rrweb events, in capture order."""

    # Opus: ge=0 against the model's PositiveIntegerField: a negative sequence is an
    # IntegrityError from the database CHECK, which is a 500 for what the
    # schema can refuse.
    sequence: int = Field(ge=0)
    events_json: NonBlankText
    first_event_timestamp_ms: int
    last_event_timestamp_ms: int
    path: CapturedPath
    job_id: UUID | None = None


class RecordingFiltersIn(Schema):
    """Optional narrowing for the recordings list.

    A ninja ``Schema``, not the service's dataclass: ``Query[...]`` flattens a
    Schema's fields into individual optional query params, while a plain
    dataclass is taken as ONE required param called ``filters`` — which made
    every unfiltered list call a 422.
    """

    user_id: UUID | None = None
    job_id: UUID | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None
    has_events: bool | None = None


class RecordingOut(ResponseSchema):
    """A recording as the admin list and the player header show it."""

    id: UUID
    user_id: UUID
    user_email: str | None
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None
    initial_path: str
    latest_path: str
    job_id: UUID | None
    viewport_width: int | None
    viewport_height: int | None
    event_count: int
    compressed_bytes: int
    payload_available: bool


class PaginatedRecordingList(ResponseSchema):
    """Wire contract for a paginated list of recordings."""

    results: list[RecordingOut]
    count: int
    page: int
    page_size: int
    total_pages: int


class ChunkOut(ResponseSchema):
    """Acknowledgement that a batch was stored."""

    id: UUID
    recording_id: UUID
    sequence: int
    event_count: int
    compressed_bytes: int


class RecordingEventsOut(ResponseSchema):
    """Every event of a recording, concatenated in playback order."""

    recording_id: UUID
    events: list[ReplayEvent]


class FrontendErrorIn(Schema):
    """An uncaught browser error, reported with the replay it happened in."""

    message: NonBlankText
    stack: str | None = None
    path: NonBlankText
    session_replay_id: UUID | None = None


class FrontendErrorOut(ResponseSchema):
    """The persisted error's id, so a browser log can name it."""

    error_id: UUID | None
