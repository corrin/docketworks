"""Data-version push: every write reaches the stream, coalesced to two events.

A version bump that never leaves the server is the dangerous failure — the tab
keeps rendering data it believes is current and nothing anywhere reports an
error. Every test here asserts a publish HAPPENED and how many, never merely
that the write succeeded.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.core.cache import caches
from django.db import connection
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import AppError
from apps.job.models import Job
from apps.operations.api import DATASET_VERSION_PROVIDERS, current_data_versions
from apps.operations.push import (
    DATA_VERSION_SOURCE_MODELS,
    DATA_VERSIONS_EVENT,
    PUBLISH_COALESCE_SECONDS,
    PUBLISH_LOCK_KEY,
    publish_data_versions_now,
    schedule_data_versions_publish,
)
from apps.purchasing.models import Stock

pytestmark = pytest.mark.django_db

CaptureOnCommit = Callable[..., AbstractContextManager[list[Callable[[], None]]]]


@pytest.fixture(autouse=True)
def _released_publish_lock() -> Iterator[None]:
    """Start every test inside a fresh coalescing window.

    The lock is a shared-cache key with a one-second timeout, so a leftover
    from the previous test in the same worker would silently suppress the
    publish under test.
    """
    caches["shared"].delete(PUBLISH_LOCK_KEY)
    yield
    caches["shared"].delete(PUBLISH_LOCK_KEY)


def _forget_earlier_registrations() -> None:
    """Discard on-commit registrations made before the block under test.

    ``push.py`` registers its publisher once per transaction, and pytest-django
    rolls back rather than commits, so nothing ever drains
    ``connection.run_on_commit``: a write during fixture setup would leave the
    publisher looking already-registered for the whole test and the block under
    test would observe no registration at all. Discarding is safe because a
    rolled-back transaction never runs them either.
    """
    connection.run_on_commit.clear()


def _make_stock(description: str) -> Stock:
    return Stock.objects.create(
        description=description,
        quantity=Decimal("1"),
        unit_cost=Decimal("3"),
        source="manual",
    )


def _published(send_event: MagicMock) -> list[dict[str, str]]:
    """The payload of every push, asserting channel and event name on the way."""
    payloads = []
    for call in send_event.call_args_list:
        channel, event_type, payload = call.args
        assert channel == settings.DATA_VERSIONS_CHANNEL
        assert event_type == DATA_VERSIONS_EVENT
        payloads.append(payload)
    return payloads


def test_every_provider_has_source_models() -> None:
    """The registry and the providers must not drift apart.

    A dataset whose provider gains no source models still answers the poll and
    silently never pushes — the exact failure this substrate exists to remove.
    """
    assert set(DATA_VERSION_SOURCE_MODELS) == set(DATASET_VERSION_PROVIDERS)


def test_job_save_publishes_after_commit(
    company: Company,
    office_staff: Staff,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    _forget_earlier_registrations()

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        # A Job write also cascades into the JobSummary.pdf refresh, which
        # celery would run for real here; unrelated to what this asserts.
        patch("apps.job.tasks.refresh_job_summary_pdfs_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        make_job(company, office_staff)

    assert len(_published(send_event)) == 1


def test_nothing_publishes_before_the_transaction_commits(
    company: Company,
    office_staff: Staff,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """Publishing mid-transaction would advertise versions a reader cannot read."""
    _forget_earlier_registrations()

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=False) as callbacks,
    ):
        make_job(company, office_staff)

    assert schedule_data_versions_publish in callbacks
    assert send_event.call_count == 0


def test_deletion_publishes(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """Max(updated_at) cannot see a deletion; post_delete is why it is wired."""
    item = _make_stock("Sheet 3mm")
    _forget_earlier_registrations()

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        item.delete()

    assert len(_published(send_event)) == 1


def test_untracked_update_publishes(
    company: Company,
    office_staff: Staff,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """The whole class of Job bookkeeping writes, not one instance of it.

    ``purchase_order_service`` on line receipt and ``job_service``'s
    invoice-flag reset both move ``Job.updated_at`` this way and fire no
    ``post_save``; announcing from the queryset method covers every such call
    site, including the ones not written yet.
    """
    job = make_job(company, office_staff)
    _forget_earlier_registrations()

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        Job.objects.filter(pk=job.pk).untracked_update(
            fully_invoiced=False, updated_at=timezone.now()
        )

    assert len(_published(send_event)) == 1


def test_touch_updated_at_publishes(
    company: Company,
    office_staff: Staff,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """The named freshness bump, which also bypasses save()."""
    job = make_job(company, office_staff)
    _forget_earlier_registrations()

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        Job.objects.filter(pk=job.pk).touch_updated_at(at=timezone.now())

    assert len(_published(send_event)) == 1


def test_a_burst_costs_one_leading_publish_and_one_trailing_task(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """A save storm costs two events, not one per row.

    Five rows in one transaction also register ONE on-commit callback, not
    five: every row would queue the same publisher, and each extra copy buys
    only another Redis round-trip that finds the coalescing lock held.
    """
    _forget_earlier_registrations()

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async") as trailing_task,
        django_capture_on_commit_callbacks(execute=True) as callbacks,
    ):
        for index in range(5):
            _make_stock(f"Bar {index}")

    assert sum(callback is schedule_data_versions_publish for callback in callbacks) == 1
    assert len(_published(send_event)) == 1
    trailing_task.assert_called_once_with(countdown=PUBLISH_COALESCE_SECONDS)


def test_the_trailing_publish_carries_writes_the_leading_one_could_not_see(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """The reason the trailing edge exists, asserted on its payload.

    Celery is eager under the test settings and eager mode ignores
    ``countdown``, so letting the burst dispatch the task for real would run
    the "trailing" publish during the first write and prove nothing. The
    dispatch is captured instead, and the task body run by hand at the moment
    it would really have fired.
    """
    _forget_earlier_registrations()

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        for index in range(5):
            _make_stock(f"Bar {index}")

    leading = _published(send_event)
    assert len(leading) == 1

    # A write landing inside the window the leading publish already went out
    # for — exactly the one a leading edge on its own loses.
    _forget_earlier_registrations()
    with (
        patch("apps.operations.push.send_event"),
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        _make_stock("Late arrival")

    with patch("apps.operations.push.send_event") as trailing_send:
        publish_data_versions_now()

    trailing = _published(trailing_send)
    assert trailing == [current_data_versions()]
    assert trailing != leading


def test_payload_is_the_data_versions_document(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """The push carries exactly what the poll serves, so one client path reads both."""
    _forget_earlier_registrations()

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        _make_stock("Sheet 3mm")

    assert _published(send_event) == [current_data_versions()]


def test_the_publish_callback_is_registered_robust() -> None:
    """A Redis blip must not cancel unrelated committed work.

    Django abandons every remaining on-commit callback once one raises, and
    this callback is registered by ``post_save`` — ahead of the callbacks a
    service queues later in the same transaction.
    """
    _forget_earlier_registrations()

    with patch("apps.operations.push.transaction.on_commit") as on_commit:
        _make_stock("Sheet 3mm")

    registrations = [
        call for call in on_commit.call_args_list if call.args[0] is schedule_data_versions_publish
    ]
    assert len(registrations) == 1
    assert registrations[0].kwargs == {"robust": True}


def test_a_publish_failure_is_persisted() -> None:
    """``robust=True`` hides the traceback from the caller; the ledger must not.

    Without a persisted AppError a Redis outage degrades into tabs that quietly
    stop updating, which is the failure this substrate exists to remove
    (ADR 0038).
    """
    with (
        patch("apps.operations.push.send_event", side_effect=RuntimeError("redis is down")),
        pytest.raises(RuntimeError, match="redis is down"),
    ):
        schedule_data_versions_publish()

    assert AppError.objects.filter(message__icontains="redis is down").exists()
