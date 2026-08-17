"""Posting a payroll week: the task does the work, the stream only reports it.

Opus: The provider is faked here so the whole flow — dispatch, progress events,
terminal event, the stream's replay — is asserted without a Xero tenant. What
these cannot cover is Xero's own behaviour; that is the E2E spec's job against
the demo company.
"""

import json
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from django.http import StreamingHttpResponse
from django.test import Client

from apps.accounting.types import StaffWeekPostResult
from apps.accounts.models import Staff
from apps.core.models import AppError
from apps.timesheet import tasks
from apps.timesheet.services import payroll_progress

pytestmark = pytest.mark.django_db

WEEK = date(2026, 5, 4)


class _FakeProvider:
    """An accounting provider that records what it was asked to post."""

    provider_name = "Fake"
    supports_payroll = True

    def __init__(self, results: Sequence[StaffWeekPostResult], error: Exception | None = None):
        self.results = results
        self.error = error
        self.calls: list[tuple[Sequence[UUID], date]] = []

    def post_payroll_week(
        self, staff_ids: Sequence[UUID], week_start_date: date
    ) -> Iterator[StaffWeekPostResult]:
        self.calls.append((staff_ids, week_start_date))
        if self.error is not None:
            raise self.error
        yield from self.results


def _result(
    staff_id: str,
    *,
    success: bool = True,
    work_hours: Decimal = Decimal("0"),
    leave_hours: Decimal = Decimal("0"),
    error: str | None = None,
) -> StaffWeekPostResult:
    return StaffWeekPostResult(
        staff_id=staff_id,
        staff_name="Wendy Workshop",
        success=success,
        work_hours=work_hours,
        leave_hours=leave_hours,
        error=error,
    )


def _run_task(
    monkeypatch: pytest.MonkeyPatch, provider: _FakeProvider, staff_ids: list[str]
) -> str:
    task_id = str(uuid4())
    payroll_progress.register(task_id, staff_ids, WEEK.isoformat())
    monkeypatch.setattr(tasks, "get_provider", lambda: provider)
    tasks.post_payroll_week_task(task_id, staff_ids, WEEK.isoformat())
    return task_id


def _events(task_id: str) -> list[dict[str, object]]:
    return payroll_progress.events_since(task_id, 0)


class TestPostingTask:
    def test_publishes_start_progress_complete_and_done(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        provider = _FakeProvider([_result(str(worker.id), work_hours=Decimal("8.0"))])

        task_id = _run_task(monkeypatch, provider, [str(worker.id)])

        assert [event["event"] for event in _events(task_id)] == [
            "start",
            "progress",
            "complete",
            "done",
        ]
        done = _events(task_id)[-1]
        assert done == {"event": "done", "successful": 1, "failed": 0}

    def test_a_failed_staff_member_does_not_stop_the_rest(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, other_worker: Staff
    ) -> None:
        """One unlinked employee must not strand everyone else's hours."""
        provider = _FakeProvider(
            [
                _result(str(worker.id), success=False, error="Not linked to a Xero employee"),
                _result(str(other_worker.id), work_hours=Decimal("6.5")),
            ]
        )

        task_id = _run_task(monkeypatch, provider, [str(worker.id), str(other_worker.id)])

        completions = [e for e in _events(task_id) if e["event"] == "complete"]
        assert [e["success"] for e in completions] == [False, True]
        assert completions[0]["error"] == "Not linked to a Xero employee"
        assert _events(task_id)[-1] == {"event": "done", "successful": 1, "failed": 1}

    def test_hours_stay_exact_on_the_wire(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """Hours are JSON numbers (ADR 0046) and still exact.

        Opus: These were strings, to protect figures the operator reconciles against
        Xero. The protection was in the wrong place: the rounding that can
        actually change someone's pay happens while SUMMING, which is Decimal
        all the way from the pay item, and a string quantity only moves the
        parse into every consumer. The values below are the three-decimal
        payroll precision and survive a JSON number exactly.
        """
        provider = _FakeProvider(
            [_result(str(worker.id), work_hours=Decimal("7.35"), leave_hours=Decimal("0.65"))]
        )

        task_id = _run_task(monkeypatch, provider, [str(worker.id)])

        [completion] = [e for e in _events(task_id) if e["event"] == "complete"]
        assert completion["work_hours"] == 7.35
        assert completion["leave_hours"] == 0.65
        # Opus: Numbers, not the strings this used to send: a consumer that treats a
        # quantity as text renders NaN or sorts "10" before "9".
        assert isinstance(completion["work_hours"], float)

    def test_a_batch_level_refusal_still_ends_the_run(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """A preflight failure must publish a terminal event, or the page spins forever."""
        provider = _FakeProvider([], error=ValueError("Pay items are not linked to Xero"))

        task_id = str(uuid4())
        payroll_progress.register(task_id, [str(worker.id)], WEEK.isoformat())
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)
        with pytest.raises(ValueError, match="Pay items are not linked"):
            tasks.post_payroll_week_task(task_id, [str(worker.id)], WEEK.isoformat())

        events = _events(task_id)
        assert events[-2] == {
            "event": "error",
            "message": "Pay items are not linked to Xero",
        }
        assert events[-1] == {"event": "done", "successful": 0, "failed": 1}

    def test_a_batch_level_refusal_records_which_week_and_staff_were_left_unposted(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """The log line cannot be queried later; the AppError row can.

        Opus: Progress events expire with their cache entry, so without this the
        scope of a failed payroll run — which week, which staff — is gone by
        the time anyone asks.
        """
        provider = _FakeProvider([], error=ValueError("Pay items are not linked to Xero"))
        task_id = str(uuid4())
        payroll_progress.register(task_id, [str(worker.id)], WEEK.isoformat())
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)

        with pytest.raises(ValueError):
            tasks.post_payroll_week_task(task_id, [str(worker.id)], WEEK.isoformat())

        context = AppError.objects.latest("timestamp").data
        assert context is not None
        assert context["task_id"] == task_id
        assert context["staff_ids"] == [str(worker.id)]
        assert context["week_start_date"] == WEEK.isoformat()
        assert context["successful"] == 0
        assert context["failed"] == 0

    def test_a_backend_without_payroll_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        provider = _FakeProvider([])
        provider.supports_payroll = False

        task_id = str(uuid4())
        payroll_progress.register(task_id, [str(worker.id)], WEEK.isoformat())
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)
        with pytest.raises(ValueError, match="does not support payroll"):
            tasks.post_payroll_week_task(task_id, [str(worker.id)], WEEK.isoformat())


class TestProgressChannel:
    def test_events_replay_from_an_offset(self) -> None:
        """The reason the work moved out of the request: a reconnect loses nothing."""
        task_id = str(uuid4())
        payroll_progress.register(task_id, [], WEEK.isoformat())
        payroll_progress.publish(task_id, {"event": "start", "total": 2})
        payroll_progress.publish(task_id, {"event": "progress", "current": 1})

        assert len(payroll_progress.events_since(task_id, 0)) == 2
        assert payroll_progress.events_since(task_id, 1) == [{"event": "progress", "current": 1}]
        assert payroll_progress.events_since(task_id, 2) == []

    def test_only_done_and_error_end_the_run(self) -> None:
        assert payroll_progress.is_terminal({"event": "done"}) is True
        assert payroll_progress.is_terminal({"event": "error"}) is True
        assert payroll_progress.is_terminal({"event": "progress"}) is False


class TestPostStreamEndpoint:
    def test_replays_the_runs_events_and_closes_on_done(
        self, manage_client: Client, worker: Staff
    ) -> None:
        task_id = str(uuid4())
        payroll_progress.register(task_id, [str(worker.id)], WEEK.isoformat())
        payroll_progress.publish(task_id, {"event": "start", "total": 1})
        payroll_progress.publish(task_id, {"event": "done", "successful": 1, "failed": 0})

        response = manage_client.get(f"/api/timesheets/payroll/post-staff-week/stream/{task_id}/")

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"
        assert response["X-Accel-Buffering"] == "no"
        # Opus: The test client types every response as WSGI; this endpoint streams.
        chunks = cast("Iterator[bytes]", cast("StreamingHttpResponse", response).streaming_content)
        body = b"".join(chunks).decode()
        frames = [
            json.loads(line.removeprefix("data: "))
            for line in body.split("\n\n")
            if line.startswith("data: ")
        ]
        assert frames == [
            {"event": "start", "total": 1},
            {"event": "done", "successful": 1, "failed": 0},
        ]

    def test_an_unknown_run_is_404_rather_than_an_endless_wait(self, manage_client: Client) -> None:
        response = manage_client.get(f"/api/timesheets/payroll/post-staff-week/stream/{uuid4()}/")

        assert response.status_code == 404

    def test_the_stream_is_superuser_only(self, worker_client: Client, worker: Staff) -> None:
        """It reports other staff members' pay, so office access is not enough."""
        task_id = str(uuid4())
        payroll_progress.register(task_id, [str(worker.id)], WEEK.isoformat())

        response = worker_client.get(f"/api/timesheets/payroll/post-staff-week/stream/{task_id}/")

        assert response.status_code in {401, 403}


class TestProgressChannelCrossesProcesses:
    """The writer is Celery and the reader is the web process.

    Opus: This is not a preference about cache backends. With a per-process cache the
    two never meet, and the observed failure is the worst shape available: the
    post runs to completion against Xero, the page waits on a stream that can
    never emit, and the operator's only evidence that payroll was written is a
    spinner that does not stop. They post again.

    Opus: Asserted structurally because the single-process test suite cannot
    reproduce it — `settings_test` puts both aliases on LocMem, so behaviour
    here is identical either way and only the wiring can be checked.

    Opus: The other half of the guarantee — that production's "shared" alias really
    does span processes — lives in `config/tests/test_cache_aliases.py`,
    because the layer contract keeps a domain app out of `config`.
    """

    def test_progress_uses_the_shared_cache_not_the_default_one(self) -> None:
        """Asserted on the alias, not the object.

        Opus: Django's cache handler hands out an instance per thread and discards it
        on teardown, so comparing identities is a coin flip under xdist — an
        earlier version of this test failed intermittently for that reason and
        told us nothing about the wiring it was meant to pin.
        """
        from django.core.cache import caches  # noqa: PLC0415

        assert payroll_progress._cache() is caches["shared"]
        assert caches["shared"] is not caches["default"]
