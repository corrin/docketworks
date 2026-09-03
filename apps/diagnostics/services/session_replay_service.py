"""Storage and retrieval for rrweb session replays.

Recordings and chunks are index rows in Postgres; the rrweb events themselves
are gzipped JSON on a private disk root, because a replay is written once,
read almost never, and is large enough that keeping it in the database would
put every browsing session into every pg_dump.
"""

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.file_store import PrivateFileStore
from apps.diagnostics.models import SessionReplayChunk, SessionReplayRecording

# An rrweb event is an opaque JSON object: this layer counts events and hands
# them back verbatim, and giving them a structural type here would be a claim
# about rrweb's wire format that nothing in v2 checks or needs.
type JsonValue = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None
type ReplayEvent = dict[str, JsonValue]

# Recordings deleted per pass, so the first purge after a long gap does not
# load an unbounded backlog into one task.
PURGE_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class Viewport:
    """Browser viewport at capture time; absent on clients that withheld it."""

    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class NewRecording:
    """Everything needed to open a recording."""

    user: Staff
    initial_path: str
    user_agent: str | None
    viewport: Viewport
    job_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class NewChunk:
    """One uploaded batch of rrweb events, as the client describes it."""

    recording: SessionReplayRecording
    sequence: int
    events_json: str
    first_event_timestamp_ms: int
    last_event_timestamp_ms: int
    path: str
    viewport: Viewport
    job_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RecordingFilters:
    """Optional narrowing for the recordings list."""

    user_id: UUID | None = None
    job_id: UUID | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None
    # Opus: tri-state, not a bool. A recording opened and abandoned before its
    # first flush has no events and nothing to play, so the admin player asks
    # for has_events=True; None keeps the unfiltered list every other caller
    # gets, and False is how the eventless ones are found deliberately.
    has_events: bool | None = None


class ReplayPayloadMissingError(Exception):
    """A recording's rows are here but its chunk files are not.

    The ordinary cause is a database restore: recording and chunk rows travel
    inside the dump, while the payloads live on the source host's storage root
    and only arrive if ``scripts/ops/pull_prod_files.sh`` has been run. That is
    an environment fact, not a fault, so it is a typed refusal rather than an
    unexpected error — a 500 per click would fill the AppError table with
    something no one can fix from this machine.
    """


def _store() -> PrivateFileStore:
    """Build the replay store; per call, so a settings override applies."""
    return PrivateFileStore(root=settings.SESSION_REPLAY_STORAGE_ROOT, label="session replay")


def _chunk_storage_path(recording_id: UUID, sequence: int) -> str:
    """Zero-padded so a recording's chunks sort in playback order on disk."""
    return f"{recording_id}/{sequence:06d}.json.gz"


def _decode_events(events_json: str) -> list[ReplayEvent]:
    """Parse the uploaded batch, refusing anything that is not a real batch.

    An empty array is rejected as well as a non-array: a chunk row claims a
    sequence number permanently (the unique constraint), so storing an empty
    one would burn a slot and leave a file that contributes nothing to
    playback.
    """
    # ValueError, not ruff's suggested TypeError: this is malformed data
    # arriving over the wire, not a caller passing the wrong Python type.
    decoded: JsonValue = json.loads(events_json)
    if not isinstance(decoded, list):
        raise ValueError("events_json must contain a JSON array")  # noqa: TRY004
    if not decoded:
        raise ValueError("events_json must contain at least one event")
    events: list[ReplayEvent] = []
    for event in decoded:
        if not isinstance(event, dict):
            raise ValueError("events_json must contain only JSON objects")  # noqa: TRY004
        events.append(event)
    return events


def _read_chunk_events(chunk: SessionReplayChunk) -> list[ReplayEvent]:
    """Read one chunk back, verifying it is the payload that was written.

    The checksum is not decoration. These files are pulled between machines by
    the backup and restore scripts, and a truncated chunk decompresses into a
    plausible-looking prefix; playing that back as if it were the session is
    worse than refusing it.
    """
    payload = _store().read(chunk.storage_path)
    if hashlib.sha256(payload).hexdigest() != chunk.sha256:
        raise ValueError(f"Replay chunk {chunk.id} checksum mismatch")
    return _decode_events(gzip.decompress(payload).decode("utf-8"))


def create_recording(new: NewRecording) -> SessionReplayRecording:
    """Open a recording. Chunks arrive later against its id."""
    return SessionReplayRecording.objects.create(
        user=new.user,
        initial_path=new.initial_path,
        latest_path=new.initial_path,
        user_agent=new.user_agent,
        viewport_width=new.viewport.width,
        viewport_height=new.viewport.height,
        job_id=new.job_id,
    )


@transaction.atomic
def append_chunk(new: NewChunk) -> SessionReplayChunk:
    """Store one batch of events and roll the recording's counters forward.

    The row is created first so the unique (recording, sequence) constraint
    rejects a duplicate upload before any file is written, and the file is
    written LAST so nothing that can fail comes after it. Ordered that way
    because a rollback does not remove a file: with the counter update sitting
    between the write and the commit, a failure there rolled the row back and
    left the payload, and the client's retry of that same sequence then met a
    refusal to overwrite — a 500 the client reads as transient, so the
    recording stalled on that sequence for the rest of the session.
    """
    recording = new.recording
    events = _decode_events(new.events_json)
    compressed = gzip.compress(new.events_json.encode("utf-8"), compresslevel=6)
    storage_path = _chunk_storage_path(recording.id, new.sequence)

    chunk = SessionReplayChunk.objects.create(
        recording=recording,
        sequence=new.sequence,
        first_event_timestamp_ms=new.first_event_timestamp_ms,
        last_event_timestamp_ms=new.last_event_timestamp_ms,
        event_count=len(events),
        compressed_bytes=len(compressed),
        storage_path=storage_path,
        sha256=hashlib.sha256(compressed).hexdigest(),
        path=new.path,
        job_id=new.job_id,
        viewport_width=new.viewport.width,
        viewport_height=new.viewport.height,
    )

    recording.event_count += chunk.event_count
    recording.compressed_bytes += chunk.compressed_bytes
    recording.latest_path = new.path
    recording.job_id = new.job_id or recording.job_id
    recording.viewport_width = new.viewport.width
    recording.viewport_height = new.viewport.height
    recording.save(
        update_fields=[
            "event_count",
            "compressed_bytes",
            "latest_path",
            "job_id",
            "viewport_width",
            "viewport_height",
            "last_seen_at",
        ]
    )

    # Last, and inside the transaction: overwrite=False because an existing
    # file under a sequence the database just accepted means a previous attempt
    # left a payload behind, and silently replacing it would destroy events the
    # checksum no longer matches.
    _store().write(storage_path=storage_path, payload=compressed, overwrite=False)
    return chunk


def recordings_queryset(filters: RecordingFilters) -> QuerySet[SessionReplayRecording]:
    """Build the recordings query, newest first, for the shared paginator."""
    queryset: QuerySet[SessionReplayRecording] = SessionReplayRecording.objects.select_related(
        "user"
    ).order_by("-started_at")

    if filters.user_id is not None:
        queryset = queryset.filter(user_id=filters.user_id)
    if filters.job_id is not None:
        queryset = queryset.filter(job_id=filters.job_id)
    if filters.started_after is not None:
        queryset = queryset.filter(started_at__gte=filters.started_after)
    if filters.started_before is not None:
        queryset = queryset.filter(started_at__lte=filters.started_before)
    if filters.has_events is not None:
        queryset = (
            queryset.filter(event_count__gt=0)
            if filters.has_events
            else queryset.filter(event_count=0)
        )

    return queryset


def has_payloads(recording: SessionReplayRecording) -> bool:
    """Whether this recording's events are actually on this machine.

    Stats the recording's directory, which ``write`` creates alongside the
    first payload — so it exists if and only if a chunk was ever written here.
    One syscall and no query, which matters because the admin list asks this
    for every row of every page (ADR 0054).

    It replaces a check of chunk 0's file, which answered "not on this machine"
    when only that one chunk was missing — a partial loss dressed up as an
    absent restore. The cost of the directory test is the opposite mistake: an
    empty directory left behind by an out-of-band ``rm`` of the files alone
    reports available, and the read then fails. ``delete_recordings`` removes
    the directory with the files, so nothing this code does produces one.
    """
    return _store().full_path(str(recording.id)).is_dir()


def recording_events(recording: SessionReplayRecording) -> list[ReplayEvent]:
    """Return every event of a recording, in order, ready for the player."""
    # An empty list, not a missing payload: a session opened and abandoned
    # before its first flush has nothing stored anywhere, and answering "these
    # events are not on this machine" would send a superuser after files that
    # were never written.
    if not recording.chunks.exists():
        return []
    if not has_payloads(recording):
        raise ReplayPayloadMissingError(str(recording.id))
    events: list[ReplayEvent] = []
    for chunk in recording.chunks.order_by("sequence"):
        events.extend(_read_chunk_events(chunk))
    return events


def delete_recordings(recordings: list[SessionReplayRecording]) -> int:
    """Delete recordings and the payloads behind them, files first.

    Files go first because the rows are the only index of where they live: if
    the row deletion succeeded and the unlink then failed, nothing would ever
    find those files again. Deleting a file whose row survives is merely a
    broken replay, which reads as an error the next time it is played.
    """
    store = _store()
    for recording in recordings:
        for chunk in recording.chunks.all():
            store.delete(chunk.storage_path)
        store.remove_dir_if_empty(str(recording.id))

    deleted, _ = SessionReplayRecording.objects.filter(
        id__in=[recording.id for recording in recordings]
    ).delete()
    return deleted


def purge_old_recordings(*, retention_days: int) -> int:
    """Delete every recording older than the retention window, in batches.

    Batched because the steady state is one day's worth but the first run after
    a retention window is shortened — or after capture ships — is the entire
    backlog, and loading every stale recording and all of its chunk rows into
    one Celery task's memory scales with how long nobody ran this.
    """
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted = 0
    while True:
        batch = list(
            SessionReplayRecording.objects.filter(started_at__lt=cutoff).prefetch_related("chunks")[
                :PURGE_BATCH_SIZE
            ]
        )
        if not batch:
            return deleted
        deleted += delete_recordings(batch)
