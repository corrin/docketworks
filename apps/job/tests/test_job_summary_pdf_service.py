"""JobSummary.pdf refresh service + task body (ported v1 test_job_summary_pdf_service.py).

The enqueue side (post-commit debounce) is covered in test_job_tasks.py; this
file pins the refresh service semantics (atomic write, JobFile upsert, stale
batching) and the task body's lock/queue interplay including the follow-up
requeue chaining restored in 3b-3.
"""

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from django.core.cache import caches
from django.test import override_settings

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.errors import persist_app_error
from apps.core.models import AppError
from apps.job.models import JobFile
from apps.job.services.job_summary_pdf_service import JobSummaryPdfService
from apps.job.services.workshop_pdf_service import JOB_SUMMARY_PDF_FILENAME
from apps.job.tasks import (
    JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY,
    JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY,
    refresh_job_summary_pdfs_task,
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


@pytest.fixture(autouse=True)
def _shared_cache() -> Iterator[None]:
    with override_settings(CACHES=_CACHES_WITH_SHARED):
        caches["shared"].clear()
        yield
        caches["shared"].clear()


@pytest.fixture(autouse=True)
def _workflow_folder(tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "workflow"
    folder.mkdir()
    with override_settings(DROPBOX_WORKFLOW_FOLDER=str(folder)):
        yield folder


class TestRefreshService:
    def test_refresh_writes_stable_pdf_and_job_file(
        self, company: Company, office_staff: Staff, _workflow_folder: Path
    ) -> None:
        job = make_job(company, office_staff, name="Summary Job")

        with patch(
            "apps.job.services.job_summary_pdf_service.create_workshop_pdf",
            return_value=BytesIO(b"%PDF first"),
        ):
            JobSummaryPdfService.refresh(job.id)

        path = _workflow_folder / f"Job-{job.job_number}" / "JobSummary.pdf"
        job_file = JobFile.objects.get(job=job, filename=JOB_SUMMARY_PDF_FILENAME)
        assert path.read_bytes() == b"%PDF first"
        assert job_file.file_path == f"Job-{job.job_number}/JobSummary.pdf"
        assert job_file.mime_type == "application/pdf"
        assert job_file.print_on_jobsheet is False

    def test_refresh_batches_missing_jobs_and_skips_fresh(
        self, company: Company, office_staff: Staff
    ) -> None:
        stale = make_job(company, office_staff, name="Stale Summary")
        missing = make_job(company, office_staff, name="Missing Summary")
        fresh = make_job(company, office_staff, name="Fresh Summary")
        JobFile.objects.create(
            job=fresh,
            filename=JOB_SUMMARY_PDF_FILENAME,
            file_path=f"Job-{fresh.job_number}/JobSummary.pdf",
            mime_type="application/pdf",
            print_on_jobsheet=False,
            status="active",
        )
        refreshed: list[UUID] = []

        with patch.object(JobSummaryPdfService, "refresh", side_effect=refreshed.append):
            refreshed_count, remaining = JobSummaryPdfService.refresh_stale(limit=1)

        assert refreshed_count == 1
        assert remaining is True
        assert set(refreshed).issubset({stale.id, missing.id})

    def test_refresh_upsert_reuses_existing_row(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="Upsert Job")

        with patch(
            "apps.job.services.job_summary_pdf_service.create_workshop_pdf",
            return_value=BytesIO(b"%PDF one"),
        ):
            JobSummaryPdfService.refresh(job.id)
        with patch(
            "apps.job.services.job_summary_pdf_service.create_workshop_pdf",
            return_value=BytesIO(b"%PDF two"),
        ):
            JobSummaryPdfService.refresh(job.id)

        assert JobFile.objects.filter(job=job, filename=JOB_SUMMARY_PDF_FILENAME).count() == 1


class TestRefreshTaskBody:
    def test_refresh_task_persists_failure_once(self) -> None:
        before = AppError.objects.count()
        cache = caches["shared"]
        cache.set(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY, True, timeout=60)
        with (
            patch(
                "apps.job.services.job_summary_pdf_service.JobSummaryPdfService.refresh_stale",
                side_effect=RuntimeError("summary render failed"),
            ),
            patch("apps.job.tasks._schedule_job_summary_pdf_refresh") as schedule,
            pytest.raises(RuntimeError),
        ):
            refresh_job_summary_pdfs_task()

        assert AppError.objects.count() == before + 1
        assert cache.get(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY) is None
        assert cache.get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY) is None
        schedule.assert_not_called()

    def test_refresh_task_passes_prelogged_failure_without_duplicate(self) -> None:
        cache = caches["shared"]
        cache.set(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY, True, timeout=60)
        prelogged = RuntimeError("summary render failed")
        persist_app_error(prelogged)
        before = AppError.objects.count()

        with (
            patch(
                "apps.job.services.job_summary_pdf_service.JobSummaryPdfService.refresh_stale",
                side_effect=prelogged,
            ),
            pytest.raises(RuntimeError),
        ):
            refresh_job_summary_pdfs_task()

        assert AppError.objects.count() == before
        assert cache.get(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY) is None
        assert cache.get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY) is None

    def test_refresh_task_keeps_queued_marker_when_another_run_is_active(self) -> None:
        cache = caches["shared"]
        cache.set(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY, True, timeout=60)
        cache.set(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY, True, timeout=60)

        with patch(
            "apps.job.services.job_summary_pdf_service.JobSummaryPdfService.refresh_stale"
        ) as refresh_stale:
            refresh_job_summary_pdfs_task()

        refresh_stale.assert_not_called()
        assert cache.get(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY)
        assert cache.get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)

    def test_refresh_task_schedules_remaining_work_after_releasing_lock(self) -> None:
        cache = caches["shared"]

        def assert_lock_released(countdown: int) -> None:
            assert countdown == 0
            assert cache.get(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY) is None

        with (
            patch(
                "apps.job.services.job_summary_pdf_service.JobSummaryPdfService.refresh_stale",
                return_value=(1, True),
            ),
            patch(
                "apps.job.tasks._schedule_job_summary_pdf_refresh",
                side_effect=assert_lock_released,
            ) as schedule,
        ):
            refresh_job_summary_pdfs_task()

        schedule.assert_called_once_with(0)
        assert cache.get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)

    def test_refresh_task_schedules_mid_run_request_after_releasing_lock(self) -> None:
        cache = caches["shared"]

        def mark_queued_during_run(limit: int) -> tuple[int, bool]:
            assert limit == 20
            assert cache.get(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY)
            cache.set(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY, True, timeout=60)
            return 1, False

        def assert_lock_released(countdown: int) -> None:
            assert countdown == 0
            assert cache.get(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY) is None

        with (
            patch(
                "apps.job.services.job_summary_pdf_service.JobSummaryPdfService.refresh_stale",
                side_effect=mark_queued_during_run,
            ),
            patch(
                "apps.job.tasks._schedule_job_summary_pdf_refresh",
                side_effect=assert_lock_released,
            ) as schedule,
        ):
            refresh_job_summary_pdfs_task()

        schedule.assert_called_once_with(0)
        assert cache.get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)
