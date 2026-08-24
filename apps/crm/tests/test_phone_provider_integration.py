"""The phone-provider pull against the real 2talk portal (ADR 0050).

Reads only: login, CDR pages, recording download and the local archive, all
driven through ``sync_call_history`` and the app's own download endpoint, and
asserted by reading the rows and files back. Provider-side deletion
(``deleteMedia``) is outside this gate: it is irreversible on the one live
account and 2talk offers no undo, which is the ADR's opt-in exception;
``docs/rewrite-status.md`` carries that opt-in test as a task.

Three vendor facts shape the assertions, measured on 2026-08-23 against
45,637 real payloads and one live seven-day pull: the CDR mixes billing lines
(type "Add-On", no parties, status None) in with the calls; a stored call
never has a blank ``type``/``status``/``description``; and 2talk serves an
empty recording body now and then (7 of 975 recordings), which the service
records as ``archive_error`` rather than a file.
"""

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from django.http import StreamingHttpResponse
from django.test import Client
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from apps.core.environment import assert_not_production_database
from apps.crm.models import PhoneCallRecord, PhoneCallRecording, PhoneEndpoint
from apps.crm.services.phone_call_service import PhoneCallSyncResult, sync_call_history

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

# The keys the client and the upsert read off every CDR row.
_CDR_KEYS = (
    "id",
    "calldate",
    "calltime",
    "origin",
    "destination",
    "type",
    "status",
    "description",
    "seconds",
    "charge",
)


def _is_mpeg_audio(head: bytes) -> bool:
    # An MP3 file opens with an ID3 tag or an MPEG frame sync (eleven set bits).
    return head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)


@pytest.fixture(autouse=True)
def _guards(integration_credentials: None, settings: SettingsWrapper, tmp_path: Path) -> None:  # noqa: ARG001 -- the credentials fixture is the dependency: it gives the test database the real provider settings
    assert_not_production_database("the phone integration test imports calls and recordings.")
    settings.PHONE_RECORDING_STORAGE_ROOT = str(tmp_path)


def test_recent_calls_and_recordings_pull_from_the_real_portal(api: Client, tmp_path: Path) -> None:
    end = timezone.localdate()
    # Seven days: a weekend alone has no calls, and an empty window must be a
    # failure (the provider, the credentials or the window is wrong), never a pass.
    start = end - timedelta(days=7)

    result = sync_call_history(start_date=start, end_date=end)

    calls = list(PhoneCallRecord.objects.filter(call_date__range=(start, end)))
    assert calls, f"2talk returned no calls between {start} and {end}"
    # Not calls_skipped == 0: the CDR also carries billing lines (type
    # "Add-On", no parties, status None), which is_call_payload drops — one
    # such in the first seven-day window this test ran against.
    assert result.calls_saved == len(calls)
    assert result.calls_seen == len(calls)
    for call in calls:
        missing = [key for key in _CDR_KEYS if key not in call.raw_json]
        assert not missing, f"CDR row {call.provider_call_id} lacks {missing}"

    own_numbers = set(
        PhoneEndpoint.objects.filter(is_active=True).values_list("normalized_number", flat=True)
    )
    assert own_numbers, "no active PhoneEndpoint was copied from the dev database"
    classified = [call for call in calls if call.direction != PhoneCallRecord.Direction.UNKNOWN]
    assert classified, "no call in the window touched one of our endpoints"
    for call in classified:
        assert call.our_number in own_numbers

    recorded = [call for call in calls if call.raw_json.get("RecordingId")]
    assert recorded, "no call in the window carried a RecordingId"
    assert result.recordings_seen == len(recorded)

    _assert_recordings_read_back(recorded, result, tmp_path)

    _assert_served_by_the_app(api)

    # The same window again is a no-op: every call already upserted, every
    # recording already archived or already known to be empty.
    counts = (PhoneCallRecord.objects.count(), PhoneCallRecording.objects.count())
    again = sync_call_history(start_date=start, end_date=end)
    assert again.calls_seen == result.calls_seen
    assert again.calls_saved == 0
    assert again.recordings_archived == 0
    assert (PhoneCallRecord.objects.count(), PhoneCallRecording.objects.count()) == counts


def _assert_recordings_read_back(
    recorded: list[PhoneCallRecord], result: PhoneCallSyncResult, storage_root: Path
) -> None:
    """Every RecordingId has a row: an archived MPEG file, or the provider's empty body."""
    archived = 0
    empty = 0
    for call in recorded:
        recording = PhoneCallRecording.objects.get(
            provider_recording_id=str(call.raw_json["RecordingId"])
        )
        assert recording.call_id == call.id
        if recording.archive_error:
            assert recording.archived_at is None
            assert "was empty" in recording.archive_error
            empty += 1
            continue
        assert recording.archived_at is not None
        assert recording.content_type == "audio/mpeg"
        assert recording.storage_path
        stored = storage_root / recording.storage_path
        content = stored.read_bytes()
        assert len(content) == recording.byte_size
        assert recording.byte_size
        assert hashlib.sha256(content).hexdigest() == recording.sha256
        assert _is_mpeg_audio(content[:4]), f"{stored} does not open as MPEG audio"
        # 2talk records 16 kbps CBR with no header, so the length the archive
        # measured must agree with the one the byte count implies.
        assert recording.duration_ms is not None
        assert abs(recording.duration_ms - recording.byte_size * 8 / 16) < 1000
        archived += 1
    assert archived + empty == len(recorded)
    assert result.recordings_archived == archived
    assert archived, "every recording in the window came back empty"


def _assert_served_by_the_app(api: Client) -> None:
    """The app streams an archived real recording, with a strong ETag that revalidates."""
    served = PhoneCallRecording.objects.filter(archived_at__isnull=False).order_by("id").first()
    assert served is not None
    response = api.get(f"/api/crm/phone-call-recordings/{served.id}/download/")
    assert response.status_code == 200
    assert response["Content-Type"] == "audio/mpeg"
    assert response["ETag"] == f'"{served.sha256}"'
    assert isinstance(response, StreamingHttpResponse)
    assert hashlib.sha256(response.getvalue()).hexdigest() == served.sha256
    revalidated = api.get(
        f"/api/crm/phone-call-recordings/{served.id}/download/",
        HTTP_IF_NONE_MATCH=response["ETag"],
    )
    assert revalidated.status_code == 304
