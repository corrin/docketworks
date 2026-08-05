"""JobSummary.pdf refresh enqueue semantics.

The refresh task BODY is a Phase 3b-3 seam, but the enqueue side is live on
every Job.save()/CostLine write: these tests pin the post-commit dispatch,
the shared-cache queue dedup, and failure persistence with queue-key cleanup.

The "shared" cache alias is not yet wired into v2 settings (reported for
config integration); these tests override CACHES so the contract is exercised
against the alias production will use.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.cache import caches
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.models import AppError
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.tasks import (
    JOB_SUMMARY_PDF_REFRESH_BATCH_SIZE,
    JOB_SUMMARY_PDF_REFRESH_DELAY_SECONDS,
    JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY,
    request_job_summary_pdf_refresh,
)

pytestmark = pytest.mark.django_db

_CACHES_WITH_SHARED = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-default",
    },
    "shared": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-shared",
    },
}

CaptureOnCommit = Callable[..., AbstractContextManager[list[Callable[[], None]]]]


@pytest.fixture(autouse=True)
def _shared_cache() -> Iterator[None]:
    """Provide the 'shared' cache alias the tasks contract requires."""
    with override_settings(CACHES=_CACHES_WITH_SHARED):
        caches["shared"].clear()
        yield
        caches["shared"].clear()


def test_request_refresh_debounces_dispatch(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """Two refresh requests in one commit window enqueue exactly one task."""
    with (
        patch("apps.job.tasks.refresh_job_summary_pdfs_task") as task,
        django_capture_on_commit_callbacks(execute=True),
    ):
        request_job_summary_pdf_refresh()
        request_job_summary_pdf_refresh()

    assert task.apply_async.call_count == 1
    task.apply_async.assert_called_once_with(
        kwargs={"limit": JOB_SUMMARY_PDF_REFRESH_BATCH_SIZE},
        countdown=JOB_SUMMARY_PDF_REFRESH_DELAY_SECONDS,
    )
    # The queued key stays set (15-minute TTL) so later saves skip re-enqueueing.
    assert caches["shared"].get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)


def test_request_refresh_persists_dispatch_failure_and_clears_queue(
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """Broker failures persist one AppError and release the queued key for retry."""
    before = AppError.objects.count()

    with (
        patch(
            "apps.job.tasks.refresh_job_summary_pdfs_task.apply_async",
            side_effect=RuntimeError("broker unavailable"),
        ),
        pytest.raises(RuntimeError),
        django_capture_on_commit_callbacks(execute=True),
    ):
        request_job_summary_pdf_refresh()

    assert AppError.objects.count() == before + 1
    assert caches["shared"].get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY) is None


def test_central_save_paths_poke_one_reconciler(
    job: Job,
    office_staff: Staff,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """Job.save() and CostLine writes in one commit enqueue a single refresh."""
    with (
        patch("apps.job.tasks.refresh_job_summary_pdfs_task") as task,
        django_capture_on_commit_callbacks(execute=True),
    ):
        job.name = "Renamed"
        job.save(staff=office_staff, update_fields=["name"])
        CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="adjust",
            desc="Workshop adjustment",
            quantity=Decimal("1.00"),
            unit_cost=Decimal("0.00"),
            unit_rev=Decimal("0.00"),
            accounting_date=timezone.localdate(),
            meta={"comments": "summary PDF poke"},
        )

    assert task.apply_async.call_count == 1
