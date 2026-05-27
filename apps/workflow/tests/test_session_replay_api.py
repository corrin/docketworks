import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.workflow.models import AppError, SessionReplayRecording
from apps.workflow.services.session_replay_service import (
    purge_old_recordings,
    recording_events,
)


@pytest.fixture
def office_staff(db):
    return Staff.objects.create_user(
        email="replay-office@example.test",
        password="pw",
        is_office_staff=True,
    )


@pytest.fixture
def workshop_staff(db):
    return Staff.objects.create_user(
        email="replay-workshop@example.test",
        password="pw",
        is_office_staff=False,
    )


def _client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def test_authenticated_staff_can_create_recording_and_upload_chunk(workshop_staff):
    api = _client(workshop_staff)
    create = api.post(
        "/api/session-replays/recordings/",
        data={
            "initial_path": "/kanban",
            "viewport_width": 1280,
            "viewport_height": 720,
        },
        format="json",
    )
    assert create.status_code == 201
    recording_id = create.json()["id"]

    events = [{"type": 4, "timestamp": 1}, {"type": 2, "timestamp": 2}]
    chunk = api.post(
        f"/api/session-replays/recordings/{recording_id}/chunks/",
        data={
            "sequence": 0,
            "events_json": json.dumps(events),
            "first_event_timestamp_ms": 1,
            "last_event_timestamp_ms": 2,
            "path": "/kanban",
            "viewport_width": 1280,
            "viewport_height": 720,
        },
        format="json",
    )
    assert chunk.status_code == 201

    recording = SessionReplayRecording.objects.get(id=recording_id)
    assert recording.event_count == 2
    assert recording.compressed_bytes > 0
    assert recording_events(recording) == events


def test_duplicate_chunk_sequence_is_rejected(workshop_staff):
    api = _client(workshop_staff)
    recording_id = api.post(
        "/api/session-replays/recordings/",
        data={"initial_path": "/kanban"},
        format="json",
    ).json()["id"]
    payload = {
        "sequence": 0,
        "events_json": json.dumps([{"type": 4, "timestamp": 1}]),
        "first_event_timestamp_ms": 1,
        "last_event_timestamp_ms": 1,
        "path": "/kanban",
    }

    assert (
        api.post(
            f"/api/session-replays/recordings/{recording_id}/chunks/",
            data=payload,
            format="json",
        ).status_code
        == 201
    )
    assert (
        api.post(
            f"/api/session-replays/recordings/{recording_id}/chunks/",
            data=payload,
            format="json",
        ).status_code
        == 409
    )


def test_only_office_staff_can_read_replays(office_staff, workshop_staff):
    recording = SessionReplayRecording.objects.create(
        user=workshop_staff,
        initial_path="/kanban",
        latest_path="/kanban",
    )

    assert (
        _client(workshop_staff).get("/api/session-replays/recordings/").status_code
        == 403
    )
    assert (
        _client(office_staff).get("/api/session-replays/recordings/").status_code == 200
    )
    assert (
        _client(office_staff)
        .get(f"/api/session-replays/recordings/{recording.id}/events/")
        .status_code
        == 200
    )


def test_replay_list_rejects_invalid_started_filters(office_staff):
    api = _client(office_staff)

    assert (
        api.get(
            "/api/session-replays/recordings/",
            data={"started_after": "not-a-date"},
        ).status_code
        == 400
    )
    assert (
        api.get(
            "/api/session-replays/recordings/",
            data={"started_before": "not-a-date"},
        ).status_code
        == 400
    )


def test_replay_list_filters_by_started_date(office_staff):
    old = SessionReplayRecording.objects.create(
        user=office_staff,
        initial_path="/old",
        latest_path="/old",
    )
    current = SessionReplayRecording.objects.create(
        user=office_staff,
        initial_path="/current",
        latest_path="/current",
    )
    SessionReplayRecording.objects.filter(id=old.id).update(
        started_at=timezone.now() - timedelta(days=3)
    )

    response = _client(office_staff).get(
        "/api/session-replays/recordings/",
        data={"started_after": (timezone.now() - timedelta(days=1)).isoformat()},
    )

    assert response.status_code == 200
    result_ids = {row["id"] for row in response.json()["results"]}
    assert str(current.id) in result_ids
    assert str(old.id) not in result_ids


def test_frontend_error_creates_apperror_with_replay(office_staff):
    api = _client(office_staff)
    recording = SessionReplayRecording.objects.create(
        user=office_staff,
        initial_path="/kanban",
        latest_path="/kanban",
    )

    response = api.post(
        "/api/session-replays/frontend-errors/",
        data={
            "message": "Frontend broke",
            "stack": "stack",
            "path": "/kanban",
            "session_replay_id": str(recording.id),
        },
        format="json",
    )
    assert response.status_code == 201
    error = AppError.objects.get(id=response.json()["id"])
    assert error.app == "frontend"
    assert error.session_replay_id == recording.id
    assert error.user_id == office_staff.id


def test_frontend_error_rejects_replay_owned_by_another_user(
    office_staff, workshop_staff
):
    recording = SessionReplayRecording.objects.create(
        user=workshop_staff,
        initial_path="/kanban",
        latest_path="/kanban",
    )

    response = _client(office_staff).post(
        "/api/session-replays/frontend-errors/",
        data={
            "message": "Frontend broke",
            "path": "/kanban",
            "session_replay_id": str(recording.id),
        },
        format="json",
    )

    assert response.status_code == 400
    assert not AppError.objects.filter(session_replay_id=recording.id).exists()


def test_frontend_error_rejects_unknown_replay(office_staff):
    unknown_replay_id = uuid4()

    response = _client(office_staff).post(
        "/api/session-replays/frontend-errors/",
        data={
            "message": "Frontend broke",
            "path": "/kanban",
            "session_replay_id": str(unknown_replay_id),
        },
        format="json",
    )

    assert response.status_code == 400
    assert not AppError.objects.filter(session_replay_id=unknown_replay_id).exists()


def test_purge_old_recordings_deletes_cascade(office_staff):
    old = SessionReplayRecording.objects.create(
        user=office_staff,
        initial_path="/old",
        latest_path="/old",
    )
    current = SessionReplayRecording.objects.create(
        user=office_staff,
        initial_path="/current",
        latest_path="/current",
    )
    SessionReplayRecording.objects.filter(id=old.id).update(
        started_at=timezone.now() - timedelta(days=30)
    )

    deleted = purge_old_recordings(retention_days=14)

    assert deleted >= 1
    assert not SessionReplayRecording.objects.filter(id=old.id).exists()
    assert SessionReplayRecording.objects.filter(id=current.id).exists()
