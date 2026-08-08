"""The SSE sync-progress stream: framing, terminal status and view auth.

Business risk covered: the frontend's sync dialog decides "sync succeeded"
versus "sync failed" from the terminal marker this generator emits — a wrong
sync_status silently hides a failed sync from the office. The view sits
outside ninja, so its auth and anti-buffering headers are asserted here or
nowhere.
"""

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from django.http import StreamingHttpResponse
from django.test import Client

from apps.xero.sync_stream import generate_xero_sync_events

URL = "/api/xero/sync-stream/"


class _StubSyncService:
    """Scripted stand-in for XeroSyncService.

    ``task_ids`` is consumed one per get_active_task_id call (empty list means
    "no active sync"); ``buffer`` behaves like the real per-task message list,
    sliced by since_index.
    """

    def __init__(self, task_ids: list[str | None], buffer: list[dict[str, object]]) -> None:
        self._task_ids = task_ids
        self._buffer = buffer

    def get_active_task_id(self) -> str | None:
        return self._task_ids.pop(0) if self._task_ids else None

    def get_messages(self, _task_id: str, since_index: int = 0) -> list[dict[str, object]]:
        return self._buffer[since_index:]


def _payloads(events: list[str]) -> list[dict[str, Any]]:
    """Decode the JSON out of the SSE data frames (keep-alives carry none)."""
    return [json.loads(event[len("data: ") :]) for event in events if event.startswith("data: ")]


def _run_generator(stub: _StubSyncService, *, token_present: bool = True) -> list[dict[str, Any]]:
    with (
        patch("apps.xero.sync_stream.has_stored_token", return_value=token_present),
        patch("apps.xero.sync_stream.XeroSyncService", stub),
        # The module only uses time for sleep; patching the module reference
        # (not time.sleep globally) keeps the poll loop instant.
        patch("apps.xero.sync_stream.time"),
    ):
        return _payloads(list(generate_xero_sync_events()))


class TestGenerateXeroSyncEvents:
    def test_no_stored_token_emits_one_error_event_and_ends(self) -> None:
        payloads = _run_generator(_StubSyncService([], []), token_present=False)

        assert len(payloads) == 1
        assert payloads[0]["severity"] == "error"
        assert "authenticate" in payloads[0]["message"].lower()

    def test_buffered_messages_stream_then_success_marker(self) -> None:
        buffer: list[dict[str, object]] = [
            {"severity": "info", "message": "Synced contacts"},
            {"severity": "info", "message": "Synced invoices"},
        ]
        # Active on attach, lock released on the first poll: the loop drains
        # the buffer, then the empty follow-up read triggers the terminal
        # marker.
        stub = _StubSyncService(["task-1", None, None], buffer)

        payloads = _run_generator(stub)

        messages = [p["message"] for p in payloads]
        assert messages == [
            "Starting Xero sync",
            "Synced contacts",
            "Synced invoices",
            "Sync stream ended",
        ]
        terminal = payloads[-1]
        assert terminal["sync_status"] == "success"
        assert terminal["progress"] == 1.0
        assert "error_messages" not in terminal

    def test_error_severity_in_buffer_marks_the_sync_failed(self) -> None:
        buffer: list[dict[str, object]] = [
            {"severity": "info", "message": "Synced contacts"},
            {"severity": "error", "message": "Invoice sync blew up"},
        ]
        stub = _StubSyncService(["task-1", None, None], buffer)

        payloads = _run_generator(stub)

        terminal = payloads[-1]
        assert terminal["message"] == "Sync stream ended"
        assert terminal["sync_status"] == "error"
        assert terminal["error_messages"] == ["Invoice sync blew up"]


class TestStreamXeroSyncView:
    def test_anonymous_request_gets_401_json(self) -> None:
        response = Client().get(URL)

        assert response.status_code == 401
        assert response.json() == {"detail": "Authentication credentials were not provided."}

    @pytest.mark.django_db
    def test_authenticated_request_streams_events(self, api: Client) -> None:
        def one_event() -> Iterator[str]:
            yield "data: {}\n\n"

        # The real generator never returns while a sync could still start;
        # a one-event stand-in lets the response be drained.
        with patch("apps.xero.sync_stream.generate_xero_sync_events", one_event):
            response = api.get(URL)
            assert isinstance(response, StreamingHttpResponse)
            assert response.status_code == 200
            assert response["Content-Type"] == "text/event-stream"
            assert response["Cache-Control"] == "no-cache, no-transform"
            assert response["X-Accel-Buffering"] == "no"
            assert response["Content-Encoding"] == "identity"
            body = b"".join(response.streaming_content)

        assert body == b"data: {}\n\n"
