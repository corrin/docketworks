"""Session replay: ownership, chunk integrity, playback and retention.

The round trip is the point. Chunk payloads live on disk, indexed by rows in
Postgres, and every interesting failure is a disagreement between the two:
a chunk whose file has gone, a chunk whose bytes no longer match its
checksum, or a purge that drops rows and orphans payloads.
"""

import gzip
import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.test import Client

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse
from django.utils import timezone

from apps.core.models import AppError, CompanyDefaults
from apps.diagnostics.models import SessionReplayChunk, SessionReplayRecording
from apps.diagnostics.services import session_replay_service as replays

pytestmark = pytest.mark.django_db

EVENTS = [{"type": 2, "timestamp": 1}, {"type": 3, "timestamp": 2}]


@pytest.fixture(autouse=True)
def replay_storage(tmp_path: Path, settings: pytest.FixtureRequest) -> Path:
    """Point the store at a temp dir so tests never touch the real root."""
    settings.SESSION_REPLAY_STORAGE_ROOT = str(tmp_path)  # type: ignore[attr-defined]
    return tmp_path


def _open_recording(api: Client) -> str:
    response = api.post(
        "/api/session-replays/recordings/",
        data={"initial_path": "/jobs/", "viewport_width": 1280, "viewport_height": 800},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    recording_id: str = response.json()["id"]
    return recording_id


def _upload_chunk(
    api: Client, recording_id: str, *, sequence: int = 0
) -> "_MonkeyPatchedWSGIResponse":
    return api.post(
        f"/api/session-replays/recordings/{recording_id}/chunks/",
        data={
            "sequence": sequence,
            "events_json": json.dumps(EVENTS),
            "first_event_timestamp_ms": 1,
            "last_event_timestamp_ms": 2,
            "path": "/jobs/",
        },
        content_type="application/json",
    )


def test_a_recording_round_trips_through_disk_to_the_player(
    api: Client, superuser_api: Client
) -> None:
    """Capture, upload and playback: the path no unit layer can prove alone."""
    recording_id = _open_recording(api)
    assert _upload_chunk(api, recording_id).status_code == 201

    events = superuser_api.get(f"/api/session-replays/recordings/{recording_id}/events/")
    assert events.status_code == 200
    assert events.json()["events"] == EVENTS

    recording = SessionReplayRecording.objects.get(id=recording_id)
    assert recording.event_count == len(EVENTS)
    assert recording.compressed_bytes > 0


def test_the_payload_is_gzip_on_disk_not_a_database_column(
    api: Client, replay_storage: Path
) -> None:
    """The rows index the store; they are not the store."""
    recording_id = _open_recording(api)
    _upload_chunk(api, recording_id)

    chunk = SessionReplayChunk.objects.get()
    stored = replay_storage / chunk.storage_path
    assert stored.exists()
    assert json.loads(gzip.decompress(stored.read_bytes()).decode()) == EVENTS


def test_a_duplicate_sequence_is_a_conflict_not_a_second_chunk(api: Client) -> None:
    """The client's retry treats 409 as "already landed" and keeps recording."""
    recording_id = _open_recording(api)
    assert _upload_chunk(api, recording_id).status_code == 201
    assert _upload_chunk(api, recording_id).status_code == 409
    assert SessionReplayChunk.objects.count() == 1


def test_a_restored_recording_without_payloads_refuses_cleanly(
    api: Client, superuser_api: Client, replay_storage: Path
) -> None:
    """A database restore brings rows; the payloads come separately.

    284 v1 recordings arrived in the dev database this way and every click on
    one was a 500 plus an AppError row. It is an environment fact, not a
    fault, so it is a typed refusal that names the script which fixes it.
    """
    recording_id = _open_recording(api)
    _upload_chunk(api, recording_id)
    # Exactly what a restore leaves behind: rows intact, directory absent.
    shutil.rmtree(replay_storage / recording_id)

    listed = superuser_api.get("/api/session-replays/recordings/")
    assert listed.json()["results"][0]["payload_available"] is False

    response = superuser_api.get(f"/api/session-replays/recordings/{recording_id}/events/")
    assert response.status_code == 409
    assert "pull_prod_files.sh" in response.json()["detail"]


def test_a_missing_chunk_file_fails_loudly(
    api: Client, superuser_api: Client, replay_storage: Path
) -> None:
    """Silently returning a shorter session would misrepresent what happened."""
    recording_id = _open_recording(api)
    _upload_chunk(api, recording_id, sequence=0)
    _upload_chunk(api, recording_id, sequence=1)
    # A partial loss, not a wholesale absent restore: the recording still has
    # payloads, so this must stay a loud 500 rather than the typed refusal.
    second = SessionReplayChunk.objects.get(sequence=1)
    (replay_storage / second.storage_path).unlink()

    response = superuser_api.get(f"/api/session-replays/recordings/{recording_id}/events/")
    assert response.status_code == 500
    assert AppError.objects.filter(message__contains="file missing").exists()


def test_a_corrupted_chunk_fails_loudly(
    api: Client, superuser_api: Client, replay_storage: Path
) -> None:
    """A truncated file decompresses to a plausible prefix; the checksum is
    the only thing that notices."""
    recording_id = _open_recording(api)
    _upload_chunk(api, recording_id)
    stored = replay_storage / SessionReplayChunk.objects.get().storage_path
    stored.write_bytes(gzip.compress(json.dumps([{"type": 9}]).encode()))

    response = superuser_api.get(f"/api/session-replays/recordings/{recording_id}/events/")
    assert response.status_code == 500
    assert AppError.objects.filter(message__contains="checksum mismatch").exists()


def test_a_staff_member_cannot_upload_to_another_recording(
    api: Client, superuser_api: Client
) -> None:
    """Writes are owner-scoped; the 404 does not confirm the id exists."""
    recording_id = _open_recording(superuser_api)
    assert _upload_chunk(api, recording_id).status_code == 404


def test_the_list_returns_recordings_without_any_filter(api: Client, superuser_api: Client) -> None:
    """An unfiltered list is the call the admin page actually makes.

    The only superuser assertion here used to be a 403 for office staff, so
    no test ever exercised a SUCCESSFUL list — and the endpoint 422'd on every
    unfiltered request in the browser while the suite stayed green. Declaring
    the filters as a plain dataclass made ninja read them as one required
    query param rather than four optional ones.
    """
    recording_id = _open_recording(api)

    response = superuser_api.get("/api/session-replays/recordings/")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == recording_id


def test_the_list_still_narrows_when_a_filter_is_given(api: Client, superuser_api: Client) -> None:
    """The filters stay usable now that they are individually optional."""
    _open_recording(api)

    matched = superuser_api.get(f"/api/session-replays/recordings/?job_id={uuid4()}")

    assert matched.status_code == 200
    assert matched.json()["count"] == 0


def test_the_list_can_exclude_recordings_that_have_no_events(
    api: Client, superuser_api: Client
) -> None:
    """The admin player lists only recordings there is something to watch.

    A session opened and abandoned before its first flush holds no events, and
    offering it as playable is a dead click. The narrowing belongs here rather
    than in the browser: the page pages through this list, so a client-side
    filter would count kept rows against a server total and quietly shrink
    every page.
    """
    empty_id = _open_recording(api)
    played_id = _open_recording(api)
    assert _upload_chunk(api, played_id).status_code == 201

    response = superuser_api.get("/api/session-replays/recordings/?has_events=true")

    assert response.status_code == 200, response.content
    listed = [row["id"] for row in response.json()["results"]]
    assert played_id in listed
    assert empty_id not in listed


def test_the_list_can_ask_for_only_the_recordings_that_have_no_events(
    api: Client, superuser_api: Client
) -> None:
    """False is a filter, not an absent one.

    Reading the flag for truthiness would make has_events=false mean the same
    as omitting it, so the abandoned sessions could never be listed on purpose
    — which is the one query that finds capture failing for a user.
    """
    empty_id = _open_recording(api)
    played_id = _open_recording(api)
    assert _upload_chunk(api, played_id).status_code == 201

    response = superuser_api.get("/api/session-replays/recordings/?has_events=false")

    assert response.status_code == 200, response.content
    listed = [row["id"] for row in response.json()["results"]]
    assert empty_id in listed
    assert played_id not in listed


def test_reads_are_superuser_only(api: Client) -> None:
    """A replay is somebody's screen: office staff may record, not watch."""
    recording_id = _open_recording(api)
    assert api.get("/api/session-replays/recordings/").status_code == 403
    assert api.get(f"/api/session-replays/recordings/{recording_id}/events/").status_code == 403


def test_recording_is_refused_when_the_company_switched_it_off(api: Client) -> None:
    """The off-switch v1 never had, and the reason the toggle exists."""
    defaults = CompanyDefaults.get_solo()
    defaults.session_replay_enabled = False
    defaults.save(update_fields=["session_replay_enabled"])

    response = api.post(
        "/api/session-replays/recordings/",
        data={"initial_path": "/jobs/"},
        content_type="application/json",
    )
    assert response.status_code == 409
    assert not SessionReplayRecording.objects.exists()


def test_a_frontend_error_links_to_the_replay_it_happened_in(api: Client) -> None:
    """The link is what makes a browser error reproducible."""
    recording_id = _open_recording(api)
    response = api.post(
        "/api/session-replays/frontend-errors/",
        data={
            "message": "Cannot read properties of undefined",
            "path": "/jobs/",
            "session_replay_id": recording_id,
        },
        content_type="application/json",
    )
    assert response.status_code == 201

    app_error = AppError.objects.get()
    assert app_error.app == "frontend"
    assert str(app_error.session_replay_id) == recording_id


def test_a_replay_belonging_to_someone_else_is_not_linked(
    api: Client, superuser_api: Client
) -> None:
    """Otherwise a client could attach its errors to a colleague's session."""
    recording_id = _open_recording(superuser_api)
    api.post(
        "/api/session-replays/frontend-errors/",
        data={"message": "boom", "path": "/jobs/", "session_replay_id": recording_id},
        content_type="application/json",
    )

    app_error = AppError.objects.get()
    assert app_error.session_replay_id is None
    assert app_error.data is not None
    assert app_error.data["unlinked_session_replay_id"] == recording_id


def test_the_purge_deletes_payloads_as_well_as_rows(api: Client, replay_storage: Path) -> None:
    """Retention is this feature's only privacy control.

    Rows alone would leave the recordings themselves on disk forever, which is
    the failure v1's scrubber shipped.
    """
    recording_id = _open_recording(api)
    _upload_chunk(api, recording_id)
    stored = replay_storage / SessionReplayChunk.objects.get().storage_path
    assert stored.exists()

    SessionReplayRecording.objects.filter(id=recording_id).update(
        started_at=timezone.now()
        - timedelta(days=CompanyDefaults.get_solo().session_replay_retention_days + 1)
    )
    # The service, not the task: the task's close_old_connections() would drop
    # the connection this test's transaction is running on.
    replays.purge_old_recordings(
        retention_days=CompanyDefaults.get_solo().session_replay_retention_days
    )

    assert not SessionReplayRecording.objects.exists()
    assert not SessionReplayChunk.objects.exists()
    assert not stored.exists()
    assert not stored.parent.exists()


def test_the_purge_honours_a_changed_retention_setting(api: Client) -> None:
    """The window is a setting, so changing it must change what survives.

    Without this the field is a relocated literal: the purge would pass its
    own test while still deleting on a fixed 14 days.
    """
    recording_id = _open_recording(api)
    SessionReplayRecording.objects.filter(id=recording_id).update(
        started_at=timezone.now() - timedelta(days=20)
    )

    defaults = CompanyDefaults.get_solo()
    defaults.session_replay_retention_days = 30
    defaults.save(update_fields=["session_replay_retention_days"])
    replays.purge_old_recordings(
        retention_days=CompanyDefaults.get_solo().session_replay_retention_days
    )
    assert SessionReplayRecording.objects.filter(id=recording_id).exists()

    defaults.session_replay_retention_days = 7
    defaults.save(update_fields=["session_replay_retention_days"])
    replays.purge_old_recordings(
        retention_days=CompanyDefaults.get_solo().session_replay_retention_days
    )
    assert not SessionReplayRecording.objects.filter(id=recording_id).exists()


def test_a_recent_recording_survives_the_purge(api: Client) -> None:
    """The cutoff is a date, not a truncation."""
    _open_recording(api)
    replays.purge_old_recordings(
        retention_days=CompanyDefaults.get_solo().session_replay_retention_days
    )
    assert SessionReplayRecording.objects.count() == 1


@pytest.mark.usefixtures("replay_storage")
def test_a_storage_path_cannot_escape_the_root() -> None:
    """Chunk paths are server-built today; the guard is what keeps that true."""
    store = replays._store()
    with pytest.raises(ValueError, match="escapes storage root"):
        store.full_path("../outside.json.gz")
