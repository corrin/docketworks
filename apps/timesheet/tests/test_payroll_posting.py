"""Posting a payroll week: the task does the work, the stream only reports it.

Opus: The provider is faked here so the whole flow — dispatch, progress events,
terminal event, the stream's replay — is asserted without a Xero tenant. What
these cannot cover is Xero's own behaviour; that is the E2E spec's job against
the demo company.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence
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
from apps.timesheet.schemas import PayrollPostRunOut
from apps.timesheet.services import payroll_runs

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
    payroll_runs.acquire_run_claim("tenant-1", task_id)
    payroll_runs.running("tenant-1", task_id, WEEK, total=len(staff_ids))
    monkeypatch.setattr(tasks, "get_provider", lambda: provider)
    monkeypatch.setattr(tasks.refresh_payroll_after_settle_task, "apply_async", lambda **_kw: None)
    tasks.post_payroll_week_task(task_id, "tenant-1", staff_ids, WEEK.isoformat())
    return task_id


def _results(connection_id: str = "tenant-1") -> list[dict[str, object]]:
    """The per-staff outcomes as JSON — the shape the consumer actually parses.

    Opus: Dumped rather than typed, unlike ``_run``. What these tests assert about
    a result is a property of the WIRE — that hours arrive as numbers and not
    strings (ADR 0046), under the names the generated client expects — and
    reading the model's attributes would assert the model instead, passing
    whatever serialisation did.
    """
    results: list[dict[str, object]] = _run(connection_id).model_dump(mode="json")["results"]
    return results


def _run(connection_id: str = "tenant-1") -> PayrollPostRunOut:
    """The run document as the poll and the stream both serve it."""
    post = payroll_runs.read_runs(connection_id).post
    assert post is not None, "the run document should exist"
    return post


class TestOnlyOneRunPostsAtATime:
    """Two posting runs against one organisation can pay a week twice, or half of it.

    Opus: ADR 0007 has posting DELETE the existing timesheet lines before re-posting
    them, so two interleaved runs can leave a timesheet holding neither run's
    figures. ``CELERY_TASK_ACKS_LATE`` makes redelivery on a lost worker real
    (ADR 0024), and a second operator click makes a second task id — so the
    guard cannot be scoped to the task.
    """

    def test_a_redelivered_run_posts_nothing_while_another_holds_the_claim(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """The case that still reaches the task, now that a duplicate click is a 409.

        Opus: `CELERY_TASK_ACKS_LATE` makes redelivery real (ADR 0024): a worker
        that dies has its message redelivered, and by then another run may hold
        the calendar. The guard has to be inside the task for that one, and it
        must refuse BEFORE the first irreversible call — posting deletes a
        timesheet's lines before re-posting them, so two interleaved runs can
        leave a timesheet holding neither run's figures.
        """
        held = str(uuid4())
        assert payroll_runs.acquire_run_claim("tenant-1", held) is None
        provider = _FakeProvider([_result(str(worker.id))])

        run_id = str(uuid4())
        payroll_runs.running("tenant-1", run_id, WEEK, total=1)
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)
        with pytest.raises(payroll_runs.PayrollRunClaimLostError):
            tasks.post_payroll_week_task(run_id, "tenant-1", [str(worker.id)], WEEK.isoformat())

        assert provider.calls == [], "a redelivered run reached Xero while another held the claim"
        assert _run().status == "failed"
        assert "no longer holds the posting claim" in str(_run().message)

    def test_a_run_that_finished_leaves_the_claim_free_for_the_next(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        first = _FakeProvider([_result(str(worker.id))])
        _run_task(monkeypatch, first, [str(worker.id)])

        second = _FakeProvider([_result(str(worker.id))])
        _run_task(monkeypatch, second, [str(worker.id)])

        assert len(second.calls) == 1, "the finished run did not release its claim"
        assert _run().status == "succeeded"
        assert _run().successful == 1
        assert _run().failed == 0

    def test_a_run_that_failed_leaves_the_claim_free_for_the_next(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """The claim is released in a finally, or one crash blocks payroll until the TTL."""
        failing = _FakeProvider([], error=RuntimeError("Xero refused the batch"))
        with pytest.raises(RuntimeError):
            _run_task(monkeypatch, failing, [str(worker.id)])

        recovered = _FakeProvider([_result(str(worker.id))])
        _run_task(monkeypatch, recovered, [str(worker.id)])

        assert len(recovered.calls) == 1, "a failed run left the claim behind"
        assert _run().status == "succeeded"
        assert _run().successful == 1
        assert _run().failed == 0

    def test_an_expired_claim_is_takeable_so_a_redelivery_still_runs(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """A hard-killed worker cannot release its claim; the TTL is what frees it.

        Opus: Expiry is Redis's job, so this asserts what is ours: once the key is
        gone, the next delivery acquires and posts rather than refusing forever.
        """
        abandoned = str(uuid4())
        assert payroll_runs.acquire_run_claim("tenant-1", abandoned) is None
        caches["shared"].delete(payroll_runs.claim_key("tenant-1"))

        provider = _FakeProvider([_result(str(worker.id))])
        _run_task(monkeypatch, provider, [str(worker.id)])

        assert len(provider.calls) == 1
        assert _run().status == "succeeded"
        assert _run().successful == 1
        assert _run().failed == 0

    def test_renewal_refuses_once_the_claim_belongs_to_someone_else(self) -> None:
        """Renewal is what stops a live run writing on after its claim lapsed."""
        mine, theirs = str(uuid4()), str(uuid4())
        assert payroll_runs.acquire_run_claim("tenant-1", mine) is None
        payroll_runs.renew_run_claim("tenant-1", mine)

        caches["shared"].set(payroll_runs.claim_key("tenant-1"), theirs)

        with pytest.raises(payroll_runs.PayrollRunClaimLostError, match=mine):
            payroll_runs.renew_run_claim("tenant-1", mine)

    def test_releasing_never_takes_another_run_claim(self) -> None:
        """A late release from an expired run must not free the run that replaced it."""
        theirs = str(uuid4())
        assert payroll_runs.acquire_run_claim("tenant-1", theirs) is None

        payroll_runs.release_run_claim("tenant-1", str(uuid4()))

        assert payroll_runs.acquire_run_claim("tenant-1", str(uuid4())) == theirs


class TestPostingTask:
    def test_an_operator_can_tell_a_finished_run_from_a_live_one(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """Because posting again over a live run is the expensive mistake.

        Opus: This is the requirement behind the whole progress path — not "four
        events arrive in this order", which is what the deleted test asserted
        and which said nothing about whether an operator could act on them.
        """
        provider = _FakeProvider([_result(str(worker.id), work_hours=Decimal("8.0"))])

        _run_task(monkeypatch, provider, [str(worker.id)])

        assert _run().status == "succeeded"
        assert _run().completed == _run().total
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
        payroll_runs.acquire_run_claim("tenant-1", task_id)
        payroll_runs.running("tenant-1", task_id, WEEK, total=1)
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

        _run_task(monkeypatch, provider, [str(worker.id), str(other_worker.id)])

        results = _results()
        assert [r["success"] for r in results] == [False, True]
        assert results[0]["error"] == "Not linked to a Xero employee"
        assert _run().successful == 1
        assert _run().failed == 1

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

        _run_task(monkeypatch, provider, [str(worker.id)])

        [completion] = _results()
        assert completion["work_hours"] == 7.35
        assert completion["leave_hours"] == 0.65
        # Opus: Numbers, not the strings this used to send: a consumer that treats a
        # quantity as text renders NaN or sorts "10" before "9".
        assert isinstance(completion["work_hours"], float)

    def test_a_batch_level_refusal_still_ends_the_run(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff
    ) -> None:
        """A batch refusal must reach the operator carrying its message.

        Opus: This is the case that cost 15 minutes on 2026-08-20. The task failed
        in seconds with "Xero locks leave while the employee is in a draft pay
        run — delete the draft for 2026-07-13, then post again", and the
        operator saw nothing: the shape this replaces published `error` then
        `done`, `TERMINAL_EVENTS` counted `error` as terminal, so the stream
        closed before the `done` the client keys "finished" off. The client
        reconnected three times and reported "the run ended without reporting an
        outcome" — we told them we did not know, when we did.

        One terminal status carrying one message cannot lose it that way.
        """
        provider = _FakeProvider([], error=ValueError("Pay items are not linked to Xero"))

        task_id = str(uuid4())
        payroll_runs.acquire_run_claim("tenant-1", task_id)
        payroll_runs.running("tenant-1", task_id, WEEK, total=1)
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)
        with pytest.raises(ValueError, match="Pay items are not linked"):
            tasks.post_payroll_week_task(task_id, "tenant-1", [str(worker.id)], WEEK.isoformat())

        run = _run()
        assert run.status == "failed"
        assert run.message == "Pay items are not linked to Xero"

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
        payroll_runs.acquire_run_claim("tenant-1", task_id)
        payroll_runs.running("tenant-1", task_id, WEEK, total=1)
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)

        with pytest.raises(ValueError):
            tasks.post_payroll_week_task(task_id, "tenant-1", [str(worker.id)], WEEK.isoformat())

        context = AppError.objects.latest("timestamp").data
        assert context is not None
        assert context["run_id"] == task_id
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
        payroll_runs.acquire_run_claim("tenant-1", task_id)
        payroll_runs.running("tenant-1", task_id, WEEK, total=1)
        monkeypatch.setattr(tasks, "get_provider", lambda: provider)
        with pytest.raises(ValueError, match="does not support payroll"):
            tasks.post_payroll_week_task(task_id, "tenant-1", [str(worker.id)], WEEK.isoformat())


class TestRunDocument:
    """Offset replay and a terminal-event set are gone, so their tests are too.

    Opus: They pinned the two ideas the document removes — that a reader rebuilds
    a run from a log it resumes at an offset, and that a SET of event names says
    which one ended it. The second was the defect: `error` was terminal and was
    published before `done`, so the stream closed on it. ADR 0039 says a test
    entrenching a removed divergence goes with the divergence.
    """

    def test_a_reader_arriving_at_any_point_sees_the_whole_run(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, other_worker: Staff
    ) -> None:
        """The requirement the old replay-from-an-offset machinery existed to meet.

        Opus: An operator who connects late, reconnects, or reloads must see every
        staff member's outcome exactly once — not a suffix of them, and not one
        copy per reconnect. Asserted by reading the run the way any late reader
        does, rather than by exercising a log's slicing, so this survives the
        next change of transport as well as it survived this one.
        """
        provider = _FakeProvider(
            [_result(str(worker.id)), _result(str(other_worker.id), success=False, error="nope")]
        )

        _run_task(monkeypatch, provider, [str(worker.id), str(other_worker.id)])

        results = _results()
        assert [r["staff_id"] for r in results] == [str(worker.id), str(other_worker.id)]
        assert _run().status == "succeeded"

    def test_a_run_is_found_without_holding_its_id(self) -> None:
        """What makes a reload rejoin: the key is the calendar, not the run.

        Opus: The shape this replaces keyed on the run id and handed it to the
        client once. Nothing persisted it, so F5 lost the run permanently while
        its record sat in the cache for another hour.
        """
        payroll_runs.running("tenant-1", str(uuid4()), WEEK, total=1)

        assert payroll_runs.read_runs("tenant-1").post is not None
        assert payroll_runs.read_runs("other-tenant").post is None


def _drain(response: StreamingHttpResponse) -> bytes:
    """Collect an async streaming response's body from a sync test."""

    chunks = cast("AsyncIterator[bytes]", response.streaming_content)

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in chunks])

    return asyncio.run(collect())


class TestRunStreamEndpoint:
    """The stream is a subscription now, not a replay of an event log."""

    def test_it_streams_rather_than_buffering_the_whole_run(self, manage_client: Client) -> None:
        """The assertion no other tier can make.

        Opus: Django decides `is_async` by whether `iter()` accepts what it was
        given, and a SYNC generator made `__aiter__` drain the entire response
        into a list before sending a byte — under ASGI the operator saw nothing
        for the whole post, then everything at once. Measured 2026-08-20 by
        driving `config.asgi:application`: sync delivered both frames at t=2.27,
        async delivered the first at t=0.77. The E2E cannot see it, because it
        waits for content to appear and a terminal blob satisfies that.

        Note what this does NOT cover: `__iter__` has the mirror-image fallback,
        so an async iterator served over WSGI buffers identically while
        `is_async` stays true. ADR 0047 pins the server; this pins the generator.
        """
        response = manage_client.get("/api/timesheets/payroll/runs/stream/")

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"
        assert response["Content-Encoding"] == "identity"
        assert cast("StreamingHttpResponse", response).is_async, (
            "the payroll stream must be served from an async iterator, or Django "
            "buffers the whole run before sending anything"
        )
        response.close()

    def test_the_stream_is_superuser_only(self, worker_client: Client) -> None:
        """It carries other staff members' pay, so office access is not enough.

        Opus: This is also why it has its own channel rather than an event on the
        data-versions one, which authenticates any staff member — sharing would
        push everyone's pay to every logged-in worker's open stream.
        """
        response = worker_client.get("/api/timesheets/payroll/runs/stream/")

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

        assert payroll_runs._cache() is caches["shared"]
        assert caches["shared"] is not caches["default"]
