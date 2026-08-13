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
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.operations.api import DATASET_VERSION_PROVIDERS, current_data_versions
from apps.operations.push import (
    DATA_VERSION_SOURCE_MODELS,
    DATA_VERSIONS_EVENT,
    PUBLISH_LOCK_KEY,
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
    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=False),
    ):
        make_job(company, office_staff)

    assert send_event.call_count == 0


def test_deletion_publishes(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """Max(updated_at) cannot see a deletion; post_delete is why it is wired."""
    item = Stock.objects.create(
        description="Sheet 3mm", quantity=Decimal("1"), unit_cost=Decimal("2"), source="manual"
    )

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        item.delete()

    assert len(_published(send_event)) == 1


def test_touch_updated_at_publishes(
    company: Company,
    office_staff: Staff,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """The one Job bump that bypasses save(), so no post_save fires for it."""
    job = make_job(company, office_staff)

    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        Job.objects.filter(pk=job.pk).touch_updated_at(at=timezone.now())

    assert len(_published(send_event)) == 1


def test_burst_coalesces_to_a_leading_and_a_trailing_publish(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """A save storm costs two events, not one per row.

    Leading so a single edit feels instant, trailing so the last write of the
    burst is not the one that never reaches the tab. Celery runs eagerly under
    the test settings, so the trailing task executes inline.
    """
    with (
        patch("apps.operations.push.send_event") as send_event,
        django_capture_on_commit_callbacks(execute=True),
    ):
        for index in range(5):
            Stock.objects.create(
                description=f"Bar {index}",
                quantity=Decimal("1"),
                unit_cost=Decimal("3"),
                source="manual",
            )

    assert len(_published(send_event)) == 2


def test_payload_is_the_data_versions_document(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """The push carries exactly what the poll serves, so one client path reads both."""
    with (
        patch("apps.operations.push.send_event") as send_event,
        patch("apps.operations.tasks.publish_data_versions_task.apply_async"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        Stock.objects.create(
            description="Sheet 3mm",
            quantity=Decimal("1"),
            unit_cost=Decimal("2"),
            source="manual",
        )

    assert _published(send_event) == [current_data_versions()]
