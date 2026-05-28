import gzip
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.workflow.models.session_replay import (
    SessionReplayChunk,
    SessionReplayRecording,
)


def _parse_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    return UUID(str(value))


def _storage_root() -> Path:
    return Path(settings.SESSION_REPLAY_STORAGE_ROOT).resolve()


def _chunk_storage_path(recording_id: UUID, sequence: int) -> str:
    return f"{recording_id}/{sequence:06d}.json.gz"


def _full_storage_path(storage_path: str) -> Path:
    root = _storage_root()
    full_path = (root / storage_path).resolve()
    if not full_path.is_relative_to(root):
        raise ValueError("Replay chunk storage path escapes storage root")
    return full_path


def _write_chunk_file(*, storage_path: str, payload: bytes) -> None:
    full_path = _full_storage_path(storage_path)
    if full_path.exists():
        raise FileExistsError(f"Replay chunk file already exists: {storage_path}")
    full_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = full_path.with_name(f".{full_path.name}.{os.getpid()}.tmp")
    try:
        with open(temp_path, "xb") as destination:
            destination.write(payload)
        os.replace(temp_path, full_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _delete_chunk_file(storage_path: str) -> None:
    try:
        _full_storage_path(storage_path).unlink(missing_ok=True)
    except ValueError:
        pass


def _read_chunk_payload(chunk: SessionReplayChunk) -> bytes:
    full_path = _full_storage_path(chunk.storage_path)
    if not full_path.exists():
        raise ValueError(f"Replay chunk file missing: {chunk.id}")
    payload = full_path.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    if checksum != chunk.sha256:
        raise ValueError(f"Replay chunk {chunk.id} checksum mismatch")
    return payload


def create_recording(
    *,
    user,
    initial_path: str,
    user_agent: str,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
    job_id: str | None = None,
) -> SessionReplayRecording:
    return SessionReplayRecording.objects.create(
        user=user,
        initial_path=initial_path,
        latest_path=initial_path,
        user_agent=user_agent,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        job_id=_parse_uuid(job_id),
    )


@transaction.atomic
def append_chunk(
    *,
    recording: SessionReplayRecording,
    sequence: int,
    events_json: str,
    first_event_timestamp_ms: int,
    last_event_timestamp_ms: int,
    path: str,
    job_id: str | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
) -> SessionReplayChunk:
    events = json.loads(events_json)
    if not isinstance(events, list):
        raise ValueError("events_json must contain a JSON array")
    if not events:
        raise ValueError("events_json must contain at least one event")

    compressed = gzip.compress(events_json.encode("utf-8"), compresslevel=6)
    storage_path = _chunk_storage_path(recording.id, sequence)
    checksum = hashlib.sha256(compressed).hexdigest()
    file_written = False
    chunk = SessionReplayChunk.objects.create(
        recording=recording,
        sequence=sequence,
        first_event_timestamp_ms=first_event_timestamp_ms,
        last_event_timestamp_ms=last_event_timestamp_ms,
        event_count=len(events),
        compressed_bytes=len(compressed),
        storage_path=storage_path,
        sha256=checksum,
        path=path,
        job_id=_parse_uuid(job_id),
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )

    try:
        _write_chunk_file(storage_path=storage_path, payload=compressed)
        file_written = True
        recording.event_count += chunk.event_count
        recording.compressed_bytes += chunk.compressed_bytes
        recording.latest_path = path
        recording.job_id = chunk.job_id or recording.job_id
        recording.viewport_width = viewport_width
        recording.viewport_height = viewport_height
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
    except Exception:
        if file_written:
            _delete_chunk_file(storage_path)
        raise
    return chunk


def list_recordings(
    *,
    limit: int,
    offset: int,
    user_id: str | None = None,
    job_id: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
) -> dict[str, Any]:
    queryset: QuerySet[SessionReplayRecording] = (
        SessionReplayRecording.objects.select_related("user")
        .all()
        .order_by("-started_at")
    )

    if user_id:
        queryset = queryset.filter(user_id=_parse_uuid(user_id))
    if job_id:
        queryset = queryset.filter(job_id=_parse_uuid(job_id))
    if started_after:
        queryset = queryset.filter(started_at__gte=started_after)
    if started_before:
        queryset = queryset.filter(started_at__lte=started_before)

    total = queryset.count()
    results = list(queryset[offset : offset + limit])
    next_offset: str | None = None
    previous_offset: str | None = None
    if offset + limit < total:
        next_offset = str(offset + limit)
    if offset > 0:
        previous_offset = str(max(offset - limit, 0))

    return {
        "count": total,
        "next": next_offset,
        "previous": previous_offset,
        "results": results,
    }


def recording_events(recording: SessionReplayRecording) -> list[Any]:
    events: list[Any] = []
    for chunk in recording.chunks.order_by("sequence"):
        payload = _read_chunk_payload(chunk)
        decoded = gzip.decompress(payload).decode("utf-8")
        chunk_events = json.loads(decoded)
        if not isinstance(chunk_events, list):
            raise ValueError(f"Invalid event payload in chunk {chunk.id}")
        events.extend(chunk_events)
    return events


def purge_old_recordings(*, retention_days: int) -> int:
    cutoff = timezone.now() - timedelta(days=retention_days)
    recordings = list(
        SessionReplayRecording.objects.filter(started_at__lt=cutoff).prefetch_related(
            "chunks"
        )
    )
    for recording in recordings:
        for chunk in recording.chunks.all():
            _delete_chunk_file(chunk.storage_path)
        recording_dir = _full_storage_path(str(recording.id))
        if recording_dir.exists():
            try:
                recording_dir.rmdir()
            except OSError:
                pass
    deleted, _ = SessionReplayRecording.objects.filter(
        id__in=[recording.id for recording in recordings]
    ).delete()
    return deleted
