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
from django.core.cache import caches
from django.http import StreamingHttpResponse
from django.test import Client

from apps.accounting.types import PayrollMirrorScope, StaffWeekPostResult
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
        self.calls: list[tuple[str, Sequence[UUID], date]] = []
        self.mirror_calls: list[tuple[str, PayrollMirrorScope]] = []

    def payroll_connection_id(self) -> str:
        return "tenant-1"

    def sync_payroll_mirror(self, connection_id: str, scope: PayrollMirrorScope) -> None:
        self.mirror_calls.append((connection_id, scope))

    def post_payroll_week(
        self, connection_id: str, staff_ids: Sequence[UUID], week_start_date: date
    ) -> Iterator[StaffWeekPostResult]:
        self.calls.append((connection_id, staff_ids, week_start_date))
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
    monkeypatch.setattr(tasks.refresh_payroll_after_settle_task, "apply_async", lambda **_kw: None)
    tasks.post_payroll_week_task(task_id, "tenant-1", staff_ids, WEEK.isoformat())
    return task_id


def _events(task_id: str) -> list[dict[str, object]]:
    return payroll_progress.events_since(task_id, 0)


class TestOnlyOneRunPostsAtATime:
    """Two posting runs against one organisation can pay a week twice, or half of it.

    ADR 0007 has posting DELETE the existing timesheet lines before re-posting
    them, so two interleaved runs can leave a timesheet holding neither run's
    figures. ``CELERY_TASK_ACKS_LATE`` makes redelivery on a lost worker real
    (ADR 0024), and a second operator click makes a second task id — so the
    guard cannot be scoped to the task.
    """

    def test_a_second_run_posts_nothing_and_names_the_run_that_holds_it(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        held = str(uuid4())
        assert payroll_progress.acquire_run_claim("tenant-1", held) is None
        provider = _FakeProvider([_result(str(worker.id))])

        task_id = _run_task(monkeypatch, provider, [str(worker.id)])

        assert provider.calls == [], "a second run reached Xero while another held the claim"
        events = _events(task_id)
        assert [event["event"] for event in events] == ["error", "done"]
        assert held in str(events[0]["message"])
        # Terminal even when refused: the page is already watching this stream,
        # and a run that never reports is indistinguishable from a slow one.
        assert events[-1] == {"event": "done", "successful": 0, "failed": 1}

    def test_a_run_that_finished_leaves_the_claim_free_for_the_next(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        first = _FakeProvider([_result(str(worker.id))])
        _run_task(monkeypatch, first, [str(worker.id)])

        second = _FakeProvider([_result(str(worker.id))])
        task_id = _run_task(monkeypatch, second, [str(worker.id)])

        assert len(second.calls) == 1, "the finished run did not release its claim"
        assert _events(task_id)[-1] == {"event": "done", "successful": 1, "failed": 0}

    def test_a_run_that_failed_leaves_the_claim_free_for_the_next(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """The claim is released in a finally, or one crash blocks payroll until the TTL."""
        failing = _FakeProvider([], error=RuntimeError("Xero refused the batch"))
        with pytest.raises(RuntimeError):
            _run_task(monkeypatch, failing, [str(worker.id)])

        recovered = _FakeProvider([_result(str(worker.id))])
        task_id = _run_task(monkeypatch, recovered, [str(worker.id)])

        assert len(recovered.calls) == 1, "a failed run left the claim behind"
        assert _events(task_id)[-1] == {"event": "done", "successful": 1, "failed": 0}

    def test_an_expired_claim_is_takeable_so_a_redelivery_still_runs(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """A hard-killed worker cannot release its claim; the TTL is what frees it.

        Expiry is Redis's job, so this asserts what is ours: once the key is
        gone, the next delivery acquires and posts rather than refusing forever.
        """
        abandoned = str(uuid4())
        assert payroll_progress.acquire_run_claim("tenant-1", abandoned) is None
        caches["shared"].delete(payroll_progress.claim_key("tenant-1"))

        provider = _FakeProvider([_result(str(worker.id))])
        task_id = _run_task(monkeypatch, provider, [str(worker.id)])

        assert len(provider.calls) == 1
        assert _events(task_id)[-1] == {"event": "done", "successful": 1, "failed": 0}

    def test_renewal_refuses_once_the_claim_belongs_to_someone_else(self) -> None:
        """Renewal is what stops a live run writing on after its claim lapsed."""
        mine, theirs = str(uuid4()), str(uuid4())
        assert payroll_progress.acquire_run_claim("tenant-1", mine) is None
        payroll_progress.renew_run_claim("tenant-1", mine)

        caches["shared"].set(payroll_progress.claim_key("tenant-1"), theirs)

        with pytest.raises(payroll_progress.PayrollRunClaimLostError, match=mine):
            payroll_progress.renew_run_claim("tenant-1", mine)

    def test_releasing_never_takes_another_run_claim(self) -> None:
        """A late release from an expired run must not free the run that replaced it."""
        theirs = str(uuid4())
        assert payroll_progress.acquire_run_claim("tenant-1", theirs) is None

        payroll_progress.release_run_claim("tenant-1", str(uuid4()))

        assert payroll_progress.acquire_run_claim("tenant-1", str(uuid4())) == theirs


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
        assert provider.mirror_calls == [
            ("tenant-1", PayrollMirrorScope.BEFORE_POST),
            ("tenant-1", PayrollMirrorScope.AFTER_POST),
        ]

    def test_schedules_one_generic_refresh_after_xero_settles(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        provider = _FakeProvider([_result(str(worker.id))])
        scheduled: list[tuple[tuple[str, str], int]] = []
        task_id = str(uuid4())
        payroll_progress.register(task_id, [str(worker.id)], WEEK.isoformat())
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)
        monkeypatch.setattr(
            tasks.refresh_payroll_after_settle_task,
            "apply_async",
            lambda *, args, countdown: scheduled.append((args, countdown)),
        )

        tasks.post_payroll_week_task(task_id, "tenant-1", [str(worker.id)], WEEK.isoformat())

        # Past the window ADR 0007 measured Xero still recomputing in: a slip
        # read at 59s carried the pre-post figures, and only at 2m17s the new
        # ones. A shorter delay mirrors the old numbers and, firing once,
        # leaves them there.
        assert scheduled == [(("tenant-1", WEEK.isoformat()), tasks.PAYSLIP_SETTLE_DELAY_SECONDS)]
        assert tasks.PAYSLIP_SETTLE_DELAY_SECONDS > 137

    def test_settled_refresh_uses_the_same_provider_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = _FakeProvider([])
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)

        tasks.refresh_payroll_after_settle_task("tenant-1", WEEK.isoformat())

        assert provider.mirror_calls == [("tenant-1", PayrollMirrorScope.AFTER_SETTLE)]

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
            tasks.post_payroll_week_task(task_id, "tenant-1", [str(worker.id)], WEEK.isoformat())

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
            tasks.post_payroll_week_task(task_id, "tenant-1", [str(worker.id)], WEEK.isoformat())

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
            tasks.post_payroll_week_task(task_id, "tenant-1", [str(worker.id)], WEEK.isoformat())


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

    Asserted structurally because the single-process test suite cannot
    reproduce it — `settings_test` puts both aliases on LocMem, so behaviour
    here is identical either way and only the wiring can be checked.

    The other half of the guarantee — that production's "shared" alias really
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
